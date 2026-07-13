"""T023 [P] [US2] — unit tests for `touch_last_seen` (store/db.py).

Re-seeing an already-known posting must advance only `last_seen`: `first_seen`,
`state`, `updated_at`, and every content column stay exactly as they were, so a
later `state` (e.g. `interested`) is never dragged back toward `new` and
`updated_at` never claims a content change that didn't happen (FR-015). A
`job_id` the store has never seen is a no-op that returns `False`. Written
first (Constitution VII) — expected to fail until T025 implements
`touch_last_seen`.
"""

from __future__ import annotations

import pytest

from jobhunter.store import db


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


def _seed_job(job_id: str = "jsearch:job-1", **overrides) -> dict:
    db.init_db()
    job = {
        "id": job_id,
        "source": "jsearch",
        "title": "Staff Backend Engineer",
        "company": "Northwind Systems",
        "city": "Bangalore",
        "description": "Own the payments platform.",
        "salary": "40-60 LPA",
        "state": "new",
    }
    job.update(overrides)
    db.upsert_job(job)
    return db.get_job(job_id)


def test_touch_last_seen_advances_last_seen(monkeypatch):
    before = _seed_job()

    monkeypatch.setattr(db, "_now", lambda: "2026-07-20T00:00:00+00:00")
    changed = db.touch_last_seen(before["id"])

    after = db.get_job(before["id"])
    assert changed is True
    assert after["last_seen"] == "2026-07-20T00:00:00+00:00"
    assert after["last_seen"] != before["last_seen"]


def test_touch_last_seen_preserves_first_seen_state_and_updated_at(monkeypatch):
    before = _seed_job(state="interested")

    monkeypatch.setattr(db, "_now", lambda: "2099-01-01T00:00:00+00:00")
    db.touch_last_seen(before["id"])

    after = db.get_job(before["id"])
    assert after["first_seen"] == before["first_seen"]
    assert after["state"] == "interested"
    assert after["updated_at"] == before["updated_at"]


def test_touch_last_seen_preserves_content_columns():
    before = _seed_job()

    db.touch_last_seen(before["id"])

    after = db.get_job(before["id"])
    assert after["title"] == before["title"]
    assert after["company"] == before["company"]
    assert after["description"] == before["description"]
    assert after["salary"] == before["salary"]


def test_touch_last_seen_is_noop_when_id_absent():
    db.init_db()

    changed = db.touch_last_seen("jsearch:does-not-exist")

    assert changed is False
    assert db.get_job("jsearch:does-not-exist") is None
