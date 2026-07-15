"""T007 [US1] — end-to-end integration for the pipeline orchestrator.

Drives the real `run_pipeline` over a fake `JobSource` + a temp `JOBHUNTER_HOME`
store, with the network (source fetch) and LLM (embeddings) both faked and the
ntfy send patched to a counter — no live JSearch/Adzuna/Ollama/Claude call
(Constitution VII). Asserts the two stages compose into one run: a new job is
discovered and persisted, then filtered/scored, an above-threshold new job
fires exactly one alert, and `run_pipeline` returns a `PipelineSummary`
aggregating both stages under one shared run id (contracts/pipeline.md C1–C6).

Written first — expected to fail until T008 implements
`jobhunter.pipeline.run.run_pipeline`.
"""

from __future__ import annotations

import pytest

from fixtures.fake_sources import FailingJobSource, FakeJobSource, make_jsearch_posting
from jobhunter.discovery.normalize import normalize_jsearch
from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.pipeline.run import PipelineSummary, run_pipeline
from jobhunter.store import db

_FAKE_EMBEDDING = [0.1, 0.2, 0.3]


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


@pytest.fixture(autouse=True)
def _mock_embed(monkeypatch):
    monkeypatch.setattr(
        "jobhunter.embeddings.ollama.embed", lambda text, **kwargs: list(_FAKE_EMBEDDING)
    )


@pytest.fixture
def notify_calls(monkeypatch) -> list[str]:
    """Capture every ntfy send so the test can assert alert-exactly-once."""
    calls: list[str] = []
    monkeypatch.setattr("jobhunter.obs.notify", lambda message, **kwargs: calls.append(message))
    return calls


@pytest.fixture
def profile() -> Profile:
    return Profile.model_validate(
        {
            "skills": ["Python", "Distributed Systems"],
            "roles": ["Staff Backend Engineer"],
            "seniority": "senior",
            "source_resume_filename": "resume.pdf",
            "parsed_at": "2026-07-01T00:00:00+00:00",
        }
    )


@pytest.fixture
def prefs() -> Preferences:
    # Deliberately lenient so the single discovered role clears every hard
    # filter, and a 0.0 alert threshold so it is guaranteed to alert once —
    # the test asserts composition, not the scorer's numeric output.
    return Preferences.model_validate(
        {
            "hard_filters": {
                "locations": ["Bangalore"],
                "work_modes": ["remote", "hybrid", "onsite"],
                "comp_floor_lpa": 1,
                "seniority_floor": "junior",
            },
            "soft_weights": {
                "work_life_balance": 0.25,
                "stability": 0.25,
                "scope": 0.25,
                "comp": 0.25,
            },
            "alerting": {"score_threshold": 0.0, "max_alerts_per_run": 5},
        }
    )


def test_run_pipeline_discovers_then_scores_and_alerts_once(profile, prefs, notify_calls):
    source = FakeJobSource([make_jsearch_posting()])

    summary = run_pipeline([source], profile, prefs)

    # One aggregate, both stages composed under one shared run id.
    assert isinstance(summary, PipelineSummary)
    assert summary.run_id == summary.discovery.run_id == summary.scoring.run_id

    # Discovery: the one posting became one genuinely-new persisted role.
    assert summary.discovery.new == 1

    # Scoring: the newly-discovered role was scored (not filtered out) in the
    # same invocation — filter-before-score held at the pipeline level.
    assert summary.scoring.scored == 1
    assert summary.scoring.filtered_out == 0
    scored = db.list_jobs_by_state("scored")
    assert len(scored) == 1
    assert db.list_jobs_by_state("new") == []

    # Alerting: exactly one ntfy send for the above-threshold new role.
    assert summary.scoring.alerted == 1
    assert len(notify_calls) == 1


def test_run_pipeline_scores_preexisting_new_jobs_when_discovery_adds_none(
    profile, prefs, notify_calls
):
    """C4: scoring runs unconditionally — a role already in the store as
    `state='new'` (from a prior run) is scored even when this run's discovery
    surfaces the same role again as already-seen, adding nothing new."""
    source = FakeJobSource([make_jsearch_posting()])

    # First run discovers + scores the role (leaves it `state='scored'`).
    first = run_pipeline([source], profile, prefs)
    assert first.discovery.new == 1
    assert first.scoring.scored == 1

    # Second run: the same posting is now already-seen — zero new — yet the run
    # still completes both stages and re-alerts nothing (write-once alerted_at).
    second = run_pipeline([source], profile, prefs)
    assert second.discovery.new == 0
    assert second.discovery.seen == 1
    assert second.scoring.scored == 0  # nothing left in state='new' to score
    assert second.scoring.alerted == 0
    assert len(notify_calls) == 1  # still just the first run's single alert


def test_one_dead_source_isolated_healthy_source_completes_pipeline(
    profile, prefs, notify_calls
):
    """T012 [US2] — a single failing source is isolated: it lands in
    `discovery.source_failures`, the healthy source's job still flows all the
    way through scoring, and the run returns success without raising (FR-004)."""
    healthy = FakeJobSource([make_jsearch_posting()], name="jsearch")
    dead = FailingJobSource(name="adzuna", reason="HTTP 429 rate limited")

    summary = run_pipeline([healthy, dead], profile, prefs)

    # The dead source is recorded, not raised.
    assert summary.discovery.source_failures == {"adzuna": "HTTP 429 rate limited"}
    assert "jsearch" in summary.discovery.attempted_sources
    # The healthy source's job completed the full pipeline through scoring.
    assert summary.discovery.new == 1
    assert summary.scoring.scored == 1
    assert summary.scoring.alerted == 1
    assert len(notify_calls) == 1


def test_every_source_failing_still_scores_preexisting_new_jobs(
    profile, prefs, notify_calls
):
    """T012 [US2] — even when *every* discovery source fails (zero new jobs),
    scoring still runs over pre-existing `state='new'` jobs and the run
    succeeds (C4)."""
    # A role left over from a prior run, sitting unscored in the store.
    db.init_db()
    leftover = {**normalize_jsearch(make_jsearch_posting()), "state": "new"}
    db.upsert_job(leftover)

    dead_a = FailingJobSource(name="jsearch", reason="auth failed")
    dead_b = FailingJobSource(name="adzuna", reason="HTTP 500")

    summary = run_pipeline([dead_a, dead_b], profile, prefs)

    # Discovery surfaced nothing new — both sources failed, both recorded.
    assert summary.discovery.new == 0
    assert set(summary.discovery.source_failures) == {"jsearch", "adzuna"}
    # ...yet the pre-existing new job was still scored and alerted.
    assert summary.scoring.scored == 1
    assert summary.scoring.alerted == 1
    assert len(notify_calls) == 1
    assert db.list_jobs_by_state("new") == []
