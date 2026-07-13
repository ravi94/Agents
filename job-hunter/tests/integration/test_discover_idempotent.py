"""T024 [P] [US2] — integration test for idempotent re-runs (discovery/run.py).

Running discovery twice over the same fixture responses must add zero
duplicate rows: already-seen postings get only `last_seen` advanced while
`first_seen` and `state` are preserved (including a row a user has already
moved to `interested`), and the run summary distinguishes `new` from `seen`
(FR-013–015, SC-002). Written first (Constitution VII) — expected to fail
until T025/T026 wire `touch_last_seen` into the orchestrator's seen path.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from jobhunter import config
from jobhunter.discovery.run import run_discovery
from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.sources.base import RawPosting, SearchQuery
from jobhunter.store import db

JOB_ID = "staff backend engineer|northwind systems|bangalore"


class FixtureJobSource:
    """A `JobSource` stand-in that returns fixture postings, no network I/O."""

    name = "jsearch"

    def __init__(self, postings: list[RawPosting]):
        self._postings = postings
        self.received_queries: list[SearchQuery] = []

    def fetch(self, queries: list[SearchQuery]) -> list[RawPosting]:
        self.received_queries = list(queries)
        return self._postings


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


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
    return Preferences.model_validate(
        {
            "hard_filters": {
                "locations": ["Bangalore"],
                "work_modes": ["remote", "hybrid", "onsite"],
                "comp_floor_lpa": 40,
                "seniority_floor": "senior",
            },
            "soft_weights": {
                "work_life_balance": 0.25,
                "stability": 0.25,
                "scope": 0.25,
                "comp": 0.25,
            },
            "alerting": {"score_threshold": 0.7, "max_alerts_per_run": 5},
        }
    )


@pytest.fixture
def jsearch_postings(fixtures_dir) -> list[RawPosting]:
    payload = json.loads((fixtures_dir / "jsearch_response.json").read_text())
    return payload["data"]["jobs"]


def _row_count() -> int:
    with sqlite3.connect(config.db_path()) as conn:
        return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def test_second_run_adds_zero_duplicates_and_reports_seen(profile, prefs, jsearch_postings):
    source = FixtureJobSource(jsearch_postings)

    first = run_discovery([source], profile, prefs)
    assert first.new == 3
    assert _row_count() == 3

    second = run_discovery([source], profile, prefs)

    assert second.fetched == 5
    assert second.skipped == 1
    assert second.new == 0
    assert second.seen == 3
    assert _row_count() == 3, "a second run over the same fixture must add zero duplicate rows"


def test_second_run_advances_last_seen_and_preserves_first_seen(monkeypatch, profile, prefs, jsearch_postings):
    source = FixtureJobSource(jsearch_postings)

    monkeypatch.setattr(db, "_now", lambda: "2026-07-01T00:00:00+00:00")
    run_discovery([source], profile, prefs)
    first_run = db.get_job(JOB_ID)

    monkeypatch.setattr(db, "_now", lambda: "2026-07-05T00:00:00+00:00")
    run_discovery([source], profile, prefs)
    second_run = db.get_job(JOB_ID)

    assert second_run["first_seen"] == first_run["first_seen"] == "2026-07-01T00:00:00+00:00"
    assert second_run["last_seen"] == "2026-07-05T00:00:00+00:00"
    assert second_run["last_seen"] != first_run["last_seen"]
    assert second_run["updated_at"] == first_run["updated_at"], "a re-sighting is not a content update"


def test_second_run_does_not_reset_interested_state(profile, prefs, jsearch_postings):
    source = FixtureJobSource(jsearch_postings)
    run_discovery([source], profile, prefs)

    interested = db.get_job(JOB_ID)
    interested["state"] = "interested"
    db.upsert_job(interested)

    summary = run_discovery([source], profile, prefs)

    after = db.get_job(JOB_ID)
    assert after["state"] == "interested"
    assert summary.new == 0
    assert summary.seen == 3
