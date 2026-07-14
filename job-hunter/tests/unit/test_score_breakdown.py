"""T017 [P] [US2] — breakdown completeness and honesty.

Two properties the M2 fixture-level tests in `test_scorer.py` don't isolate:

1. Every scored job's breakdown carries all four `SoftWeights` components
   (`work_life_balance`, `stability`, `scope`, `comp`), each with
   `value`/`weight`/`inferred`, regardless of which data points that
   particular job happens to be missing (no salary, no determinable company
   type, ...).
2. The breakdown is meaningful on its own, not just a wrapper around
   `overall` — two jobs can land on the exact same `overall` score for very
   different reasons, and the breakdown must show those differing component
   contributions rather than collapsing to the same shape.

Written first per Constitution VII (test-first); `score_job` already exists
(T013) so these are expected to pass immediately — this file exists to lock
the explainability guarantee in place before T019 hardens the atomicity rule.
"""

from __future__ import annotations

import pytest

from jobhunter.models.preferences import (
    Alerting,
    HardFilters,
    Preferences,
    SearchPrefs,
    SoftWeights,
)
from jobhunter.models.profile import Profile
from jobhunter.scoring.scorer import score_job

COMPONENT_NAMES = ("work_life_balance", "stability", "scope", "comp")


def _profile(**overrides) -> Profile:
    payload = {
        "full_name": "Test Candidate",
        "skills": ["Python", "Django"],
        "experience": [],
        "seniority": "senior",
        "roles": ["Backend Engineer"],
        "total_years_experience": 6.0,
        "source_resume_filename": "test_resume.pdf",
        "parsed_at": "2026-01-01T00:00:00+00:00",
    }
    payload.update(overrides)
    return Profile.model_validate(payload)


def _prefs(*, soft_weights: dict | None = None, comp_floor_lpa: float = 25.0) -> Preferences:
    soft_weights = soft_weights or {
        "work_life_balance": 0.25,
        "stability": 0.25,
        "scope": 0.25,
        "comp": 0.25,
    }
    return Preferences(
        hard_filters=HardFilters(
            locations=["Bangalore"],
            work_modes=["remote", "hybrid"],
            comp_floor_lpa=comp_floor_lpa,
            seniority_floor="mid",
        ),
        soft_weights=SoftWeights(**soft_weights),
        alerting=Alerting(score_threshold=0.75, max_alerts_per_run=5),
        search=SearchPrefs(keywords=[]),
    )


def _job(**overrides) -> dict:
    payload = {
        "title": "Backend Engineer",
        "description": "Build and maintain internal services.",
        "company": "Studio9",
        "salary": None,
    }
    payload.update(overrides)
    return payload


def _generic_fake_embed(text: str, **kwargs) -> list[float]:
    return [1.0, 0.0]


def _keyed_fake_embed(vectors: dict[str, list[float]], default: list[float]):
    def fake_embed(text: str, **kwargs) -> list[float]:
        return vectors.get(text, default)

    return fake_embed


# ---------------------------------------------------------------------------
# Completeness: every scored job carries all four components, fully shaped.
# ---------------------------------------------------------------------------

_JOB_VARIANTS = {
    "salary_present_company_undeterminable": _job(salary="45 LPA", company="Studio9"),
    "salary_missing_company_undeterminable": _job(salary=None, company="Studio9"),
    "salary_present_enterprise_company": _job(
        salary="45 LPA",
        company="Global MegaCorp Enterprises Ltd",
        description="A Fortune 500 multinational public enterprise conglomerate.",
    ),
    "salary_present_startup_company": _job(
        salary="45 LPA",
        company="TinyLaunch Labs",
        description="Pre-seed early-stage startup, small founding team, seed funding.",
    ),
}


@pytest.mark.parametrize("job", _JOB_VARIANTS.values(), ids=_JOB_VARIANTS.keys())
def test_every_scored_job_breakdown_has_all_four_components_fully_shaped(monkeypatch, job):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    result = score_job(job, _profile(), _prefs())

    breakdown = result.breakdown
    assert set(breakdown.components) == set(COMPONENT_NAMES)
    for name in COMPONENT_NAMES:
        component = breakdown.components[name]
        assert 0.0 <= component.value <= 1.0
        assert isinstance(component.weight, float)
        assert isinstance(component.inferred, bool)


def test_inferred_flags_are_honest_about_proxy_vs_direct_signals(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    result = score_job(_job(salary="45 LPA"), _profile(), _prefs())

    breakdown = result.breakdown
    assert breakdown.components["stability"].inferred is True
    assert breakdown.components["work_life_balance"].inferred is True
    assert breakdown.components["scope"].inferred is False
    assert breakdown.components["comp"].inferred is False


# ---------------------------------------------------------------------------
# Meaningfulness: same overall score, different component contributions.
# ---------------------------------------------------------------------------


def test_same_overall_score_shows_differing_component_contributions(monkeypatch):
    """Two jobs land on the identical `overall` score for different reasons.

    Job A is an enterprise (high stability/wlb) with a middling scope match
    and below-floor comp; Job B is a startup (low stability/wlb) with a
    perfect scope match and a higher comp — engineered so the equal-weighted
    sum comes out identical, proving the breakdown carries information the
    single `overall` number doesn't.
    """
    prefs = _prefs(
        soft_weights={
            "work_life_balance": 0.25,
            "stability": 0.25,
            "scope": 0.25,
            "comp": 0.25,
        },
        comp_floor_lpa=25.0,
    )
    profile = _profile()
    profile_text = " ".join(profile.skills + list(profile.roles))

    job_a = _job(
        title="Senior Backend Engineer",
        description=(
            "A Fortune 500 multinational public enterprise conglomerate "
            "listed on NYSE."
        ),
        company="Global MegaCorp Enterprises Ltd",
        salary="10 LPA",  # comp = 10/25 = 0.4
    )
    job_a_text = f"{job_a['title']} {job_a['description']}"
    monkeypatch.setattr(
        "jobhunter.embeddings.ollama.embed",
        _keyed_fake_embed(
            {job_a_text: [1.0, 0.0], profile_text: [0.0, 1.0]},  # orthogonal -> scope 0.5
            default=[1.0, 0.0],
        ),
    )
    result_a = score_job(job_a, profile, prefs)

    job_b = _job(
        title="Backend Engineer",
        description=(
            "Pre-seed early-stage startup, small founding team, seed funding, "
            "building our MVP."
        ),
        company="TinyLaunch Labs",
        salary="16.25 LPA",  # comp = 16.25/25 = 0.65
    )
    job_b_text = f"{job_b['title']} {job_b['description']}"
    monkeypatch.setattr(
        "jobhunter.embeddings.ollama.embed",
        _keyed_fake_embed(
            {job_b_text: [1.0, 0.0], profile_text: [1.0, 0.0]},  # identical -> scope 1.0
            default=[1.0, 0.0],
        ),
    )
    result_b = score_job(job_b, profile, prefs)

    breakdown_a, breakdown_b = result_a.breakdown, result_b.breakdown
    assert breakdown_a.overall == pytest.approx(breakdown_b.overall, abs=1e-6)

    differing = [
        name
        for name in COMPONENT_NAMES
        if not (
            breakdown_a.components[name].value
            == pytest.approx(breakdown_b.components[name].value, abs=1e-6)
        )
    ]
    assert len(differing) >= 2, (
        "same overall score but breakdown components collapsed to the same "
        f"contributions: {differing}"
    )
