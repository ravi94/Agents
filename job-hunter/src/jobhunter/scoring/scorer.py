"""T013 [US1] — the composite job scorer (`score_job`).

Implements the frozen contract in
``specs/003-job-scoring-filtering/contracts/scoring_algorithm.md`` and the
``ScoreBreakdown``/``ComponentScore`` shapes in ``data-model.md``:

- ``comp``   — ``min(salary_lpa / comp_floor_lpa, 1.0)`` when a salary is
  present, else ``0.5`` neutral; ``inferred=False``.
- ``scope``  — cosine similarity between the local-Ollama embedding of the
  job's title+description and of the profile's skills+roles, rescaled from
  ``[-1, 1]`` to ``[0, 1]``; keyword-overlap fallback when ``embed()`` returns
  ``None``; ``inferred=False``.
- ``stability`` / ``work_life_balance`` — fixed company-type → signal lookup,
  ``0.5`` neutral when undeterminable; always ``inferred=True``.
- ``overall`` — the plain weighted sum of the four component values against the
  ``prefs.yaml`` soft weights, copied onto the breakdown verbatim and NEVER
  renormalized even when the weights don't sum to 1.0.

The embedding call is made through the ``embeddings.ollama`` module (not a
direct ``from ... import embed``) so tests can monkeypatch
``jobhunter.embeddings.ollama.embed`` and no live Ollama call is ever made.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import numpy as np
from pydantic import BaseModel, ConfigDict

from jobhunter.embeddings import ollama
from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile

# Soft-weight components, in the order the contract enumerates them.
COMPONENT_NAMES = ("work_life_balance", "stability", "scope", "comp")

# Company-type proxy signals inferred from the job's title/description/company.
_ENTERPRISE_SIGNALS = (
    "fortune 500",
    "fortune500",
    "multinational",
    "public enterprise",
    "publicly traded",
    "publicly-traded",
    "public company",
    "listed on",
    "nyse",
    "nasdaq",
    "conglomerate",
    "enterprise",
    "large enterprise",
    "global leader",
    "50,000 employees",
)
_STARTUP_SIGNALS = (
    "startup",
    "start-up",
    "pre-seed",
    "preseed",
    "seed funding",
    "seed-stage",
    "early-stage",
    "early stage",
    "founding team",
    "series a",
    "series seed",
    "bootstrapped",
    "our mvp",
)

# Fixed company-type → stability/work-life-balance signal tables. A larger,
# public-company proxy scores higher on stability than an early-stage startup;
# an undeterminable company type yields the neutral 0.5 (handled below).
_STABILITY_BY_TYPE = {"enterprise": 0.9, "midsize": 0.6, "startup": 0.3}
_WLB_BY_TYPE = {"enterprise": 0.6, "midsize": 0.65, "startup": 0.45}
_NEUTRAL = 0.5

# A profile skill counts as "matched" when its rescaled [0, 1] similarity to
# the job text clears this threshold. Chosen so a near-identical embedding
# (cosine ~0.94 → ~0.97 rescaled) matches while an opposite one (cosine -1.0 →
# 0.0 rescaled) does not.
_MATCH_THRESHOLD = 0.6

_SALARY_RE = re.compile(r"[-+]?\d*\.?\d+")
_WORD_RE = re.compile(r"[a-z0-9]+")


class ComponentScore(BaseModel):
    """One weighted component of the composite score (see data-model.md)."""

    model_config = ConfigDict(extra="forbid")

    value: float
    weight: float
    inferred: bool


class ScoreBreakdown(BaseModel):
    """The self-contained breakdown persisted into the ``breakdown`` column."""

    model_config = ConfigDict(extra="forbid")

    overall: float
    components: dict[str, ComponentScore]
    computed_at: str


class ScoreResult(BaseModel):
    """In-memory result of scoring one job: the breakdown plus matched skills."""

    model_config = ConfigDict(extra="forbid")

    breakdown: ScoreBreakdown
    matched_skills: list[str]


def score_job(job: dict, profile: Profile, prefs: Preferences) -> ScoreResult:
    """Score one job against the candidate profile and preferences.

    Deterministic and side-effect free: given the same inputs it always
    produces the same breakdown and matched-skills list. Never makes a live
    Ollama call directly — it goes through ``embeddings.ollama.embed`` and
    falls back to keyword overlap whenever that returns ``None``.
    """
    job_text = f"{job.get('title', '')} {job.get('description', '')}".strip()
    profile_text = " ".join(profile.skills + list(profile.roles))

    job_vec = ollama.embed(job_text)

    scope_value = _scope(job_text, profile_text, job_vec)
    matched = _matched_skills(job_text, profile.skills, job_vec)
    comp_value = _comp(job.get("salary"), prefs.hard_filters.comp_floor_lpa)
    stability_value, wlb_value = _company_signals(job)

    weights = prefs.soft_weights
    components = {
        "work_life_balance": ComponentScore(
            value=wlb_value, weight=weights.work_life_balance, inferred=True
        ),
        "stability": ComponentScore(
            value=stability_value, weight=weights.stability, inferred=True
        ),
        "scope": ComponentScore(
            value=scope_value, weight=weights.scope, inferred=False
        ),
        "comp": ComponentScore(
            value=comp_value, weight=weights.comp, inferred=False
        ),
    }

    overall = sum(c.value * c.weight for c in components.values())

    breakdown = ScoreBreakdown(
        overall=overall,
        components=components,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )
    return ScoreResult(breakdown=breakdown, matched_skills=matched)


# ---------------------------------------------------------------------------
# comp
# ---------------------------------------------------------------------------


def _comp(salary, comp_floor_lpa: float) -> float:
    """`min(salary / floor, 1.0)` when a salary is present, else neutral 0.5."""
    salary_lpa = _parse_salary_lpa(salary)
    if salary_lpa is None:
        return _NEUTRAL
    if comp_floor_lpa <= 0:
        return 1.0
    return min(salary_lpa / comp_floor_lpa, 1.0)


def _parse_salary_lpa(salary) -> float | None:
    """Parse the leading number out of a salary value (e.g. ``"45 LPA"``)."""
    if salary is None:
        return None
    if isinstance(salary, (int, float)):
        return float(salary)
    match = _SALARY_RE.search(str(salary))
    return float(match.group()) if match else None


# ---------------------------------------------------------------------------
# scope
# ---------------------------------------------------------------------------


def _scope(job_text: str, profile_text: str, job_vec: list[float] | None) -> float:
    """Cosine similarity rescaled to [0, 1]; keyword-overlap fallback."""
    profile_vec = ollama.embed(profile_text) if job_vec is not None else None
    if job_vec is not None and profile_vec is not None:
        return _rescale(_cosine(job_vec, profile_vec))
    return _keyword_overlap(job_text, profile_text)


# ---------------------------------------------------------------------------
# matched_skills
# ---------------------------------------------------------------------------


def _matched_skills(
    job_text: str, skills: list[str], job_vec: list[float] | None
) -> list[str]:
    """Profile skills clearing the similarity threshold, best-first.

    Empty list (never ``None``) when nothing clears the threshold. Falls back
    to keyword overlap when the job embedding is unavailable.
    """
    if job_vec is None:
        job_lower = job_text.lower()
        return [skill for skill in skills if skill.lower() in job_lower]

    scored: list[tuple[float, str]] = []
    for skill in skills:
        skill_vec = ollama.embed(skill)
        if skill_vec is None:
            continue
        similarity = _rescale(_cosine(job_vec, skill_vec))
        if similarity >= _MATCH_THRESHOLD:
            scored.append((similarity, skill))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [skill for _, skill in scored]


# ---------------------------------------------------------------------------
# stability / work_life_balance
# ---------------------------------------------------------------------------


def _company_signals(job: dict) -> tuple[float, float]:
    """Return ``(stability, work_life_balance)`` from the company-type proxy."""
    company_type = _infer_company_type(job)
    if company_type is None:
        return _NEUTRAL, _NEUTRAL
    return _STABILITY_BY_TYPE[company_type], _WLB_BY_TYPE[company_type]


def _infer_company_type(job: dict) -> str | None:
    """Best-effort company-type inference from the job's text; ``None`` if unclear."""
    text = " ".join(
        str(job.get(key, "")) for key in ("title", "description", "company")
    ).lower()
    enterprise = sum(signal in text for signal in _ENTERPRISE_SIGNALS)
    startup = sum(signal in text for signal in _STARTUP_SIGNALS)
    if enterprise > startup:
        return "enterprise"
    if startup > enterprise:
        return "startup"
    return None


# ---------------------------------------------------------------------------
# math helpers
# ---------------------------------------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]; ``0.0`` for a degenerate (zero) vector."""
    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _rescale(cosine: float) -> float:
    """Map a cosine similarity from [-1, 1] onto [0, 1], clamped."""
    return max(0.0, min(1.0, (cosine + 1.0) / 2.0))


def _keyword_overlap(job_text: str, profile_text: str) -> float:
    """Jaccard token overlap between two texts, in [0, 1]."""
    job_tokens = set(_WORD_RE.findall(job_text.lower()))
    profile_tokens = set(_WORD_RE.findall(profile_text.lower()))
    if not job_tokens or not profile_tokens:
        return 0.0
    union = job_tokens | profile_tokens
    return len(job_tokens & profile_tokens) / len(union)
