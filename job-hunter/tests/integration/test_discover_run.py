"""T013 [US1] — integration test for single-source discovery (discovery/run.py).

End-to-end fetch → normalize → dedup → persist against a fixture `JobSource`
(no live call) and a temp `JOBHUNTER_HOME`: new rows land with `state=new`,
`first_seen`/`last_seen` set and equal, and null `score`; the run reports a
`fetched`/`new`/`skipped` summary; `--dry-run` (here, `dry_run=True`) writes
nothing. Written first (Constitution VII) — expected to fail until T020
implements `discovery.run.run_discovery`.
"""

from __future__ import annotations

import json

import pytest

from jobhunter.discovery.run import run_discovery
from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.sources.base import RawPosting, SearchQuery
from jobhunter.store import db


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


def test_new_run_persists_new_jobs_with_summary(profile, prefs, jsearch_postings):
    source = FixtureJobSource(jsearch_postings)

    summary = run_discovery([source], profile, prefs)

    # 5 raw postings; 1 is unnormalizable (missing title+company); the
    # "-dup" posting collapses into its counterpart within the run, leaving
    # 3 genuinely new records.
    assert summary.fetched == 5
    assert summary.skipped == 1
    assert summary.new == 3
    assert summary.seen == 0

    stored = db.get_job("staff backend engineer|northwind systems|bangalore")
    assert stored is not None
    assert stored["state"] == "new"
    assert stored["first_seen"] == stored["last_seen"]
    assert stored["score"] is None


def test_dry_run_reports_summary_but_writes_nothing(profile, prefs, jsearch_postings):
    source = FixtureJobSource(jsearch_postings)

    summary = run_discovery([source], profile, prefs, dry_run=True)

    assert summary.fetched == 5
    assert summary.new == 3

    db.init_db()
    assert db.get_job("staff backend engineer|northwind systems|bangalore") is None
