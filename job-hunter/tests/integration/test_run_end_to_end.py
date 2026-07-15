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

from fixtures.fake_sources import FakeJobSource, make_jsearch_posting
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
