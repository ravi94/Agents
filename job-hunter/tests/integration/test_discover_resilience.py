"""T030 [US3] — integration test for multi-source resilience (discovery/run.py).

Two fixture sources, one raising `SourceError`: the run MUST complete (no
exception escapes `run_discovery`), persist the healthy source's new jobs,
and record the failed source in `RunSummary.source_failures` — a partial
result is a success, never a whole-run failure (FR-017–018). Separately, the
same role fed from both sources through a full run collapses to a single
stored record (cross-source dedup, FR-013). Written first (Constitution VII)
— expected to fail until T031–T033 (Adzuna adapter, normalization, and
multi-source orchestration) land.
"""

from __future__ import annotations

import json

import pytest

from jobhunter.discovery.run import run_discovery
from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.sources.base import RawPosting, SearchQuery, SourceError
from jobhunter.store import db


class FixtureJobSource:
    """A `JobSource` stand-in that returns fixture postings, no network I/O."""

    def __init__(self, name: str, postings: list[RawPosting]):
        self.name = name
        self._postings = postings

    def fetch(self, queries: list[SearchQuery]) -> list[RawPosting]:
        return self._postings


class FailingJobSource:
    """A `JobSource` stand-in whose `fetch` always raises `SourceError`."""

    def __init__(self, name: str, reason: str):
        self.name = name
        self._reason = reason

    def fetch(self, queries: list[SearchQuery]) -> list[RawPosting]:
        raise SourceError(self._reason)


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


def test_run_completes_and_stores_healthy_source_when_other_fails(profile, prefs, fixtures_dir):
    jsearch_payload = json.loads((fixtures_dir / "jsearch_response.json").read_text())
    healthy = FixtureJobSource("jsearch", jsearch_payload["data"]["jobs"])
    failing = FailingJobSource("adzuna", "rate limited after bounded retries")

    summary = run_discovery([healthy, failing], profile, prefs)

    assert summary.attempted_sources == ["jsearch", "adzuna"]
    assert summary.source_failures == {"adzuna": "rate limited after bounded retries"}
    # Only the healthy source's 5 postings were fetched; the failing source
    # never reaches the fetched/normalize count.
    assert summary.fetched == 5
    assert summary.new == 3

    stored = db.get_job("staff backend engineer|northwind systems|bangalore")
    assert stored is not None
    assert stored["state"] == "new"


def test_same_role_from_both_sources_is_stored_once(profile, prefs, fixtures_dir):
    payload = json.loads((fixtures_dir / "source_dupe_pair.json").read_text())
    jsearch_source = FixtureJobSource("jsearch", payload["jsearch"]["data"]["jobs"])
    adzuna_source = FixtureJobSource("adzuna", payload["adzuna"]["results"])

    summary = run_discovery([jsearch_source, adzuna_source], profile, prefs)

    assert summary.fetched == 2
    assert summary.skipped == 0
    assert summary.new == 1
    assert not summary.source_failures

    # The richer (Adzuna) copy wins and is stored under its own stable id;
    # the JSearch composite id for the same role was never separately stored.
    assert db.get_job("adzuna:4021559120") is not None
    assert db.get_job("senior data engineer|vertex analytics|bangalore") is None
