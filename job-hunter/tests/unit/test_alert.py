"""T021 [P] [US3] — unit tests for the alert-gating step (`scoring/alert.py`).

`run_alerts(jobs, prefs, *, path=None)` is the gate between a `state=scored`
job and its (at most one, ever) ntfy notification (data-model.md "State
transitions (M3 scope)"; FR-009). A job qualifies iff `alerted_at is None`
and `score is not None` and `score >= prefs.alerting.score_threshold`;
qualifying jobs are processed in `jobs` order, capped at
`prefs.alerting.max_alerts_per_run` per call, and each notified job is
stamped write-once via `store.db.mark_alerted` so it can never alert again
regardless of future rescoring (the "rerun" scenario, FR-007/FR-009). These
tests exercise `run_alerts` against a real (temp) SQLite store — only
`jobhunter.obs.notify` is mocked — so `mark_alerted`'s write-once semantics
are genuinely exercised, not assumed.

Written first (Constitution VII) — expected to fail until T025/T026
implement `scoring.alert.run_alerts` / `store.db.mark_alerted`.
"""

from __future__ import annotations

import pytest
import yaml

from jobhunter.models.preferences import Preferences
from jobhunter.scoring.alert import run_alerts
from jobhunter.store import db


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


@pytest.fixture
def prefs(fixtures_dir) -> Preferences:
    data = yaml.safe_load((fixtures_dir / "scoring_prefs.yaml").read_text())
    return Preferences.model_validate(data)


@pytest.fixture
def notify_calls(monkeypatch):
    calls: list[str] = []

    def fake_notify(message):
        calls.append(message)

    monkeypatch.setattr("jobhunter.obs.notify", fake_notify, raising=False)
    return calls


def _seed_scored_job(job_id: str, score: float, *, path) -> dict:
    """Insert a freshly-scored job row (state=scored, alerted_at NULL)."""
    db.upsert_job(
        {
            "id": job_id,
            "title": f"Senior Backend Engineer ({job_id})",
            "state": "scored",
            "score": score,
        },
        path=path,
    )
    return db.get_job(job_id, path=path)


def test_notifies_and_stamps_alerted_at_when_score_at_or_above_threshold(
    prefs, notify_calls
):
    path = db.init_db()
    job = _seed_scored_job("scoring:alert-above", prefs.alerting.score_threshold, path=path)
    assert job["alerted_at"] is None

    alerted_count = run_alerts([job], prefs, path=path)

    assert alerted_count == 1
    assert len(notify_calls) == 1
    stored = db.get_job("scoring:alert-above", path=path)
    assert stored["alerted_at"] is not None


def test_does_not_notify_when_score_below_threshold(prefs, notify_calls):
    path = db.init_db()
    below = prefs.alerting.score_threshold - 0.1
    job = _seed_scored_job("scoring:alert-below", below, path=path)

    alerted_count = run_alerts([job], prefs, path=path)

    assert alerted_count == 0
    assert notify_calls == []
    stored = db.get_job("scoring:alert-below", path=path)
    assert stored["alerted_at"] is None


def test_never_realerts_once_alerted_at_is_already_set(prefs, notify_calls):
    path = db.init_db()
    job = _seed_scored_job("scoring:alert-once", prefs.alerting.score_threshold, path=path)

    first_count = run_alerts([job], prefs, path=path)
    assert first_count == 1
    assert len(notify_calls) == 1

    already_alerted = db.get_job("scoring:alert-once", path=path)
    assert already_alerted["alerted_at"] is not None
    stamped_at = already_alerted["alerted_at"]

    # Regardless of the job's current score, an already-alerted job must
    # never notify again (FR-009's "never re-alert" guarantee).
    second_count = run_alerts([already_alerted], prefs, path=path)

    assert second_count == 0
    assert len(notify_calls) == 1  # no additional notification sent
    unchanged = db.get_job("scoring:alert-once", path=path)
    assert unchanged["alerted_at"] == stamped_at


def test_max_alerts_per_run_cap_leaves_remaining_jobs_untouched(prefs, notify_calls):
    path = db.init_db()
    capped_prefs = prefs.model_copy(
        update={"alerting": prefs.alerting.model_copy(update={"max_alerts_per_run": 1})}
    )
    threshold = capped_prefs.alerting.score_threshold
    jobs = [
        _seed_scored_job(f"scoring:alert-cap-{i}", threshold, path=path) for i in range(3)
    ]

    alerted_count = run_alerts(jobs, capped_prefs, path=path)

    assert alerted_count == 1
    assert len(notify_calls) == 1

    stored = [db.get_job(job["id"], path=path) for job in jobs]
    stamped = [row for row in stored if row["alerted_at"] is not None]
    untouched = [row for row in stored if row["alerted_at"] is None]
    assert len(stamped) == 1
    assert len(untouched) == 2
    # The cap respects `jobs` order: only the first qualifying job is alerted.
    assert stored[0]["alerted_at"] is not None
