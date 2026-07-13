"""T023 [US3] — integration test for job-record round-trip (store/db.py).

A record written via `upsert_job` must read back unchanged via `get_job`
(US3 scenario 3): `state` defaults to `new`, the `first_seen`/`last_seen`/
`updated_at` timestamps are populated, and the store persists across separate
connections/runs (FR-011). Written first (Constitution VII) — expected to fail
until T024. Uses only the public `store.db` API (no raw SQL).
"""

import pytest

from jobhunter.store import db


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


@pytest.fixture
def sample_job() -> dict:
    return {
        "id": "jsearch:abc123",
        "source": "jsearch",
        "title": "Senior Backend Engineer",
        "company": "Acme",
        "location": "Bangalore, India",
        "city": "Bangalore",
        "country": "India",
        "work_mode": "hybrid",
        "description": "Build and scale payment services.",
        "employment_type": "full_time",
        "salary": "60-80 LPA",
        "apply_url": "https://example.com/apply/abc123",
    }


def test_written_record_reads_back_unchanged(sample_job):
    db.init_db()
    db.upsert_job(sample_job)

    got = db.get_job(sample_job["id"])

    assert got is not None
    # Every field we supplied comes back byte-for-byte.
    for key, value in sample_job.items():
        assert got[key] == value, f"{key} changed on round-trip"


def test_state_defaults_to_new_when_unset(sample_job):
    db.init_db()
    db.upsert_job(sample_job)

    got = db.get_job(sample_job["id"])
    assert got["state"] == "new"


def test_timestamps_are_populated_on_insert(sample_job):
    db.init_db()
    db.upsert_job(sample_job)

    got = db.get_job(sample_job["id"])
    for ts in ("first_seen", "last_seen", "updated_at"):
        assert got[ts], f"{ts} must be populated on insert"


def test_unscored_fields_default_to_null(sample_job):
    db.init_db()
    db.upsert_job(sample_job)

    got = db.get_job(sample_job["id"])
    # Score/explainability fields are populated by later milestones, null now.
    for field in ("score", "breakdown", "matched_skills", "reason"):
        assert got[field] is None


def test_get_missing_job_returns_none():
    db.init_db()
    assert db.get_job("does-not-exist") is None


def test_record_persists_across_separate_connections(sample_job):
    # First "run": init + write.
    db.init_db()
    db.upsert_job(sample_job)

    # Second "run": a fresh call path (new connection) still sees the record,
    # and re-init does not wipe it.
    db.init_db()
    got = db.get_job(sample_job["id"])

    assert got is not None
    assert got["title"] == sample_job["title"]
