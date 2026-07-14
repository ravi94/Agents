"""T009 [P] [US1] — unit tests for the composite job scoring algorithm.

Exercises `scoring/scorer.py`'s `score_job(job, profile, prefs) -> ScoreResult`
against the frozen contract in `specs/003-job-scoring-filtering/contracts/
scoring_algorithm.md` and `data-model.md` §ScoreBreakdown/ComponentScore:

- `comp`: `min(salary_lpa / comp_floor_lpa, 1.0)` when a salary is present,
  else `0.5` neutral; `inferred=False`.
- `scope`: cosine similarity between the embedding of the job's title+
  description and the embedding of the profile's skills+roles, rescaled from
  `[-1, 1]` to `[0, 1]`; falls back to keyword overlap when `embed()` returns
  `None`; `inferred=False`.
- `stability` / `work_life_balance`: looked up from a fixed company-type
  signal table, `0.5` neutral when undeterminable; always `inferred=True`.
- `overall`: the plain weighted sum of the four component values against the
  `prefs.yaml` soft weights, copied onto the breakdown verbatim and NEVER
  renormalized even when the weights don't sum to 1.0.

Written first per Constitution VII (test-first) — this file is expected to
fail right now with an import error, since `src/jobhunter/scoring/scorer.py`
does not exist yet. T013 implements `scorer.py` to make these tests pass.

Assumptions made explicit here for T013's implementer (not independently
verified elsewhere in the repo):
- `score_job` computes `job_text = job["title"] + " " + job["description"]`
  and `profile_text = " ".join(profile.skills + profile.roles)` verbatim,
  per this task's brief — these are the exact strings the mocked `embed()`
  in the scope tests below key off of.
- Salary strings look like `"<number> LPA"` (e.g. `"45 LPA"`, `"12.5 LPA"`);
  `score_job` parses the leading number and ignores the unit suffix.
- `embed()` is called more than once per `score_job` run (job text, profile
  text, and once per profile skill for `matched_skills`) — the fake `embed`
  used in the scope-precision tests below returns different vectors keyed by
  exact input text, with a generic fallback vector for any other text (e.g.
  individual skill lookups for `matched_skills`, which this file does not
  otherwise assert on).
"""

from __future__ import annotations

import json
import logging
import math
from logging.handlers import RotatingFileHandler

import pytest

from jobhunter import config, obs
from jobhunter.models.preferences import (
    Alerting,
    HardFilters,
    Preferences,
    SearchPrefs,
    SoftWeights,
)
from jobhunter.models.profile import Profile
from jobhunter.scoring.scorer import (
    ComponentScore,
    ScoreBreakdown,
    format_breakdown,
    score_job,
    to_job_fields,
)


@pytest.fixture
def _isolated_run_log(monkeypatch, tmp_path):
    """Configure a real run log under an isolated home (T016 trace tests)."""
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))
    obs.configure_run_logging()
    yield
    root = logging.getLogger("jobhunter")
    for handler in list(root.handlers):
        if isinstance(handler, RotatingFileHandler):
            root.removeHandler(handler)
            handler.close()


def _flush() -> None:
    for handler in logging.getLogger("jobhunter").handlers:
        handler.flush()

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


def _prefs(*, comp_floor_lpa: float = 25.0, soft_weights: dict | None = None) -> Preferences:
    soft_weights = soft_weights or {
        "work_life_balance": 0.2,
        "stability": 0.2,
        "scope": 0.35,
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
    """A fake `embed` that never returns None and ignores its input text.

    Used in tests that don't care about scope precision (comp tests,
    stability/work_life_balance tests) — just needs to let `score_job` run
    to completion without hitting a live Ollama endpoint.
    """
    return [1.0, 0.0]


def _keyed_fake_embed(vectors: dict[str, list[float]], default: list[float]):
    """Build a fake `embed` returning a controlled vector per exact input text.

    Falls back to `default` for any text not in `vectors` (e.g. per-skill
    `matched_skills` lookups this file doesn't assert on) so cosine similarity
    math elsewhere in `score_job` never blows up on a shape mismatch.
    """

    def fake_embed(text: str, **kwargs) -> list[float]:
        return vectors.get(text, default)

    return fake_embed


def _none_fake_embed(text: str, **kwargs) -> None:
    return None


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_score_breakdown_has_all_four_components_with_full_shape(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    result = score_job(_job(salary="45 LPA"), _profile(), _prefs())

    breakdown = result.breakdown
    assert set(breakdown.components.keys()) == set(COMPONENT_NAMES)
    for name in COMPONENT_NAMES:
        component = breakdown.components[name]
        assert 0.0 <= component.value <= 1.0
        assert isinstance(component.weight, float)
        assert isinstance(component.inferred, bool)
    assert isinstance(breakdown.computed_at, str) and breakdown.computed_at != ""


# ---------------------------------------------------------------------------
# comp component
# ---------------------------------------------------------------------------


def test_comp_caps_at_one_when_salary_exceeds_floor(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    result = score_job(_job(salary="50 LPA"), _profile(), _prefs(comp_floor_lpa=25.0))

    comp = result.breakdown.components["comp"]
    assert comp.value == pytest.approx(1.0)
    assert comp.inferred is False


def test_comp_scales_with_floor_when_salary_present_and_below_floor(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    result = score_job(_job(salary="12.5 LPA"), _profile(), _prefs(comp_floor_lpa=25.0))

    comp = result.breakdown.components["comp"]
    assert comp.value == pytest.approx(0.5)
    assert comp.inferred is False


def test_comp_is_neutral_when_salary_missing(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    result = score_job(_job(salary=None), _profile(), _prefs(comp_floor_lpa=25.0))

    comp = result.breakdown.components["comp"]
    # Same numeric value as the scaled case above (0.5) but via the neutral
    # "no salary data" code path, not the division path — asserted alongside
    # the scaled-salary test above so the two can't silently collapse into
    # the same behavior for the wrong reason.
    assert comp.value == pytest.approx(0.5)
    assert comp.inferred is False


# ---------------------------------------------------------------------------
# scope component
# ---------------------------------------------------------------------------


def test_scope_rescales_identical_vectors_to_one(monkeypatch):
    job = _job(title="Senior Backend Engineer", description="Payments platform.")
    profile = _profile(skills=["Python"], roles=["Backend Engineer"])
    job_text = f"{job['title']} {job['description']}"
    profile_text = " ".join(profile.skills + profile.roles)
    same_vector = [1.0, 0.0]

    fake_embed = _keyed_fake_embed(
        {job_text: same_vector, profile_text: same_vector}, default=same_vector
    )
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", fake_embed)

    result = score_job(job, profile, _prefs())

    scope = result.breakdown.components["scope"]
    assert scope.value == pytest.approx(1.0, abs=1e-6)
    assert scope.inferred is False


def test_scope_rescales_opposite_vectors_to_zero(monkeypatch):
    job = _job(title="Senior Backend Engineer", description="Payments platform.")
    profile = _profile(skills=["Python"], roles=["Backend Engineer"])
    job_text = f"{job['title']} {job['description']}"
    profile_text = " ".join(profile.skills + profile.roles)

    fake_embed = _keyed_fake_embed(
        {job_text: [1.0, 0.0], profile_text: [-1.0, 0.0]}, default=[1.0, 0.0]
    )
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", fake_embed)

    result = score_job(job, profile, _prefs())

    scope = result.breakdown.components["scope"]
    assert scope.value == pytest.approx(0.0, abs=1e-6)


def test_scope_rescales_orthogonal_vectors_to_half(monkeypatch):
    job = _job(title="Senior Backend Engineer", description="Payments platform.")
    profile = _profile(skills=["Python"], roles=["Backend Engineer"])
    job_text = f"{job['title']} {job['description']}"
    profile_text = " ".join(profile.skills + profile.roles)

    fake_embed = _keyed_fake_embed(
        {job_text: [1.0, 0.0], profile_text: [0.0, 1.0]}, default=[1.0, 0.0]
    )
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", fake_embed)

    result = score_job(job, profile, _prefs())

    scope = result.breakdown.components["scope"]
    assert scope.value == pytest.approx(0.5, abs=1e-6)


def test_scope_falls_back_to_keyword_overlap_when_embed_unavailable(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _none_fake_embed)

    result = score_job(
        _job(title="Senior Backend Engineer", description="Python, Django, AWS."),
        _profile(),
        _prefs(),
    )

    scope = result.breakdown.components["scope"]
    assert 0.0 <= scope.value <= 1.0


# ---------------------------------------------------------------------------
# stability / work_life_balance (inferred, company-type lookup)
# ---------------------------------------------------------------------------


def test_stability_and_wlb_are_neutral_when_company_type_undeterminable(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    result = score_job(
        _job(
            title="Backend Engineer",
            description="Build and maintain internal services. Python, PostgreSQL.",
            company="Studio9",
        ),
        _profile(),
        _prefs(),
    )

    stability = result.breakdown.components["stability"]
    wlb = result.breakdown.components["work_life_balance"]
    assert stability.value == pytest.approx(0.5)
    assert wlb.value == pytest.approx(0.5)


def test_stability_and_wlb_are_always_marked_inferred(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    neutral_result = score_job(
        _job(title="Backend Engineer", description="Build things.", company="Studio9"),
        _profile(),
        _prefs(),
    )
    enterprise_result = score_job(
        _job(
            title="Backend Engineer",
            description=(
                "A Fortune 500 multinational public enterprise conglomerate "
                "with over 50,000 employees worldwide, listed on NYSE."
            ),
            company="Global MegaCorp Enterprises Ltd",
        ),
        _profile(),
        _prefs(),
    )

    for result in (neutral_result, enterprise_result):
        assert result.breakdown.components["stability"].inferred is True
        assert result.breakdown.components["work_life_balance"].inferred is True


def test_stability_scores_higher_for_enterprise_than_early_stage_startup(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    enterprise_result = score_job(
        _job(
            title="Backend Engineer",
            description=(
                "A Fortune 500 multinational public enterprise conglomerate "
                "with over 50,000 employees worldwide, listed on NYSE."
            ),
            company="Global MegaCorp Enterprises Ltd",
        ),
        _profile(),
        _prefs(),
    )
    startup_result = score_job(
        _job(
            title="Backend Engineer",
            description=(
                "Pre-seed early-stage startup, small founding team of 3, "
                "seed funding, building our MVP."
            ),
            company="TinyLaunch Labs",
        ),
        _profile(),
        _prefs(),
    )

    enterprise_stability = enterprise_result.breakdown.components["stability"].value
    startup_stability = startup_result.breakdown.components["stability"].value
    assert enterprise_stability > startup_stability


# ---------------------------------------------------------------------------
# overall: weighted sum, no renormalization
# ---------------------------------------------------------------------------


def test_overall_is_the_weighted_sum_of_component_values(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    result = score_job(_job(salary="45 LPA"), _profile(), _prefs())

    breakdown = result.breakdown
    recomputed = sum(c.value * c.weight for c in breakdown.components.values())
    assert breakdown.overall == pytest.approx(recomputed)


def test_soft_weights_are_copied_verbatim_and_not_renormalized(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    # Deliberately sums to 0.8, not 1.0 — proves overall is capped by the
    # weight sum rather than rescaled back up to make full use of [0, 1].
    under_summed_weights = {
        "work_life_balance": 0.2,
        "stability": 0.2,
        "scope": 0.2,
        "comp": 0.2,
    }
    prefs = _prefs(soft_weights=under_summed_weights)

    result = score_job(_job(salary="45 LPA"), _profile(), prefs)

    breakdown = result.breakdown
    for name in COMPONENT_NAMES:
        assert breakdown.components[name].weight == pytest.approx(
            under_summed_weights[name]
        )
    assert breakdown.overall <= sum(under_summed_weights.values()) + 1e-9
    assert not math.isclose(breakdown.overall, 1.0)


# ---------------------------------------------------------------------------
# to_job_fields (T019): score/breakdown/matched_skills travel together
# ---------------------------------------------------------------------------


def test_to_job_fields_derives_score_and_breakdown_from_the_same_result(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    result = score_job(_job(salary="45 LPA"), _profile(), _prefs())
    fields = to_job_fields(result)

    assert set(fields) == {"score", "breakdown", "matched_skills"}
    assert fields["score"] == pytest.approx(result.breakdown.overall)

    breakdown = json.loads(fields["breakdown"])
    assert breakdown["overall"] == pytest.approx(result.breakdown.overall)
    assert set(breakdown["components"]) == set(COMPONENT_NAMES)

    assert json.loads(fields["matched_skills"]) == result.matched_skills


# ---------------------------------------------------------------------------
# format_breakdown (T020): the top contributing factor, legible without a
# separate query (SC-004).
# ---------------------------------------------------------------------------


def _breakdown(**component_overrides: tuple[float, float, bool]) -> ScoreBreakdown:
    """Build a `ScoreBreakdown` from `{name: (value, weight, inferred)}`."""
    components = {
        name: ComponentScore(value=value, weight=weight, inferred=inferred)
        for name, (value, weight, inferred) in component_overrides.items()
    }
    overall = sum(c.value * c.weight for c in components.values())
    return ScoreBreakdown(
        overall=overall, components=components, computed_at="2026-01-01T00:00:00+00:00"
    )


def test_format_breakdown_names_the_highest_weighted_contribution():
    # comp has the higher raw value (1.0 vs scope's 0.9), but scope's weighted
    # contribution (0.9*0.5=0.45) still edges out comp's (1.0*0.4=0.40) —
    # proving the helper ranks by value*weight, not raw component value alone.
    breakdown = _breakdown(
        work_life_balance=(0.1, 0.05, True),
        stability=(0.1, 0.05, True),
        scope=(0.9, 0.5, False),
        comp=(1.0, 0.4, False),
    )

    rendered = format_breakdown(breakdown)

    assert rendered.startswith("scope")
    assert "stability" not in rendered


def test_format_breakdown_includes_the_numeric_contribution():
    breakdown = _breakdown(
        work_life_balance=(0.5, 0.2, True),
        stability=(0.5, 0.2, True),
        scope=(0.8, 0.35, False),
        comp=(0.5, 0.25, False),
    )

    rendered = format_breakdown(breakdown)

    assert "0.80" in rendered  # scope's raw value
    assert "0.35" in rendered  # scope's weight


# ---------------------------------------------------------------------------
# observability (T016): the embeddings call is traced; its fallback is logged
# ---------------------------------------------------------------------------


def test_embeddings_call_is_traced(monkeypatch, _isolated_run_log):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _generic_fake_embed)

    score_job(_job(salary="45 LPA"), _profile(), _prefs())
    _flush()

    contents = config.log_path().read_text()
    assert "embeddings.embed" in contents
    assert "duration_ms" in contents


def test_embeddings_fallback_is_logged_when_embed_returns_none(monkeypatch, _isolated_run_log):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _none_fake_embed)

    score_job(_job(salary="45 LPA"), _profile(), _prefs())
    _flush()

    contents = config.log_path().read_text()
    assert "embeddings.embed" in contents
    assert "fall" in contents.lower()  # "falling back" / "fallback" logged
