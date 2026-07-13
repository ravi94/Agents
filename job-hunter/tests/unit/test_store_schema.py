"""T022 [US3] — unit tests for job-store schema creation (store/db.py).

`init_db()` must create the `jobs` table with every column defined in
data-model.md, stamp `PRAGMA user_version`, and be idempotent: a second init
reuses the existing store and never wipes previously written rows (FR-011, US3
scenarios 1–2). Written first (Constitution VII) — expected to fail until T024.
"""

import sqlite3

import pytest

from jobhunter import config
from jobhunter.store import db

# The full Job Record shape (data-model.md §"Entity: Job Record"). If a column
# is added/removed there, this list is the test's source of truth.
EXPECTED_COLUMNS = {
    "id",
    "source",
    "title",
    "company",
    "location",
    "city",
    "country",
    "work_mode",
    "description",
    "employment_type",
    "salary",
    "apply_url",
    "score",
    "breakdown",
    "matched_skills",
    "reason",
    "state",
    "first_seen",
    "last_seen",
    "updated_at",
}


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


def _table_info(db_file):
    with sqlite3.connect(db_file) as conn:
        return {row[1]: row for row in conn.execute("PRAGMA table_info(jobs)")}


def test_init_db_creates_jobs_db_file():
    assert not config.db_path().exists()

    db.init_db()

    assert config.db_path().exists()


def test_jobs_table_has_every_data_model_column():
    db.init_db()

    columns = _table_info(config.db_path())
    assert set(columns) == EXPECTED_COLUMNS


def test_id_is_primary_key():
    db.init_db()

    # PRAGMA table_info row: (cid, name, type, notnull, dflt_value, pk)
    id_row = _table_info(config.db_path())["id"]
    assert id_row[5] == 1, "id must be the PRIMARY KEY (dedup/idempotency key)"


def test_state_defaults_to_new():
    db.init_db()

    state_row = _table_info(config.db_path())["state"]
    notnull, default = state_row[3], state_row[4]
    assert notnull == 1, "state must be NOT NULL"
    assert default is not None and "new" in default, "state must default to 'new'"


def test_init_db_sets_schema_version():
    db.init_db()

    with sqlite3.connect(config.db_path()) as conn:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert user_version == db.SCHEMA_VERSION
    assert user_version > 0, "schema version must be a positive integer"


def test_init_db_is_idempotent_and_preserves_rows():
    db.init_db()

    # Write a row directly (NOT NULL columns supplied), then re-init.
    with sqlite3.connect(config.db_path()) as conn:
        conn.execute(
            "INSERT INTO jobs (id, first_seen, last_seen, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("job-1", "2026-07-13T00:00:00", "2026-07-13T00:00:00", "2026-07-13T00:00:00"),
        )
        conn.commit()

    db.init_db()  # second init must not wipe or recreate

    with sqlite3.connect(config.db_path()) as conn:
        rows = conn.execute("SELECT id FROM jobs").fetchall()
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert rows == [("job-1",)], "existing rows must survive a re-init (never wiped)"
    assert version == db.SCHEMA_VERSION
