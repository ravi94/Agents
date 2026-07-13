"""T004 [P] [Foundational] — unit tests for the `alerted_at` schema migration.

`init_db` must create the `alerted_at` column directly on a fresh store, and
migrate an existing pre-M3 (v1) store — no `alerted_at` column — via
`ALTER TABLE`, without disturbing any rows already in it (data-model.md
"New column: alerted_at"; research.md §1). `PRAGMA user_version` reads `2`
afterward, whether the store was created fresh or migrated. Written first
(Constitution VII) — expected to fail until T005 implements the migration in
`store/db.py`.
"""

from __future__ import annotations

import sqlite3

import pytest

from jobhunter import config
from jobhunter.store import db

# Pre-M3 (v1) `jobs` table shape — identical to store/db.py's current
# `_CREATE_TABLE`, minus `alerted_at` — used to simulate a store that
# predates this migration.
_V1_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    source          TEXT,
    title           TEXT,
    company         TEXT,
    location        TEXT,
    city            TEXT,
    country         TEXT,
    work_mode       TEXT,
    description     TEXT,
    employment_type TEXT,
    salary          TEXT,
    apply_url       TEXT,
    score           REAL,
    breakdown       TEXT,
    matched_skills  TEXT,
    reason          TEXT,
    state           TEXT NOT NULL DEFAULT 'new',
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
"""


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


def _table_info(db_file):
    with sqlite3.connect(db_file) as conn:
        return {row[1]: row for row in conn.execute("PRAGMA table_info(jobs)")}


def _seed_v1_store(db_file):
    config.ensure_home()
    with sqlite3.connect(db_file) as conn:
        conn.execute(_V1_CREATE_TABLE)
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "INSERT INTO jobs (id, first_seen, last_seen, updated_at) VALUES (?, ?, ?, ?)",
            ("job-1", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()


def test_init_db_on_fresh_store_creates_alerted_at_directly():
    db.init_db()

    columns = _table_info(config.db_path())
    assert "alerted_at" in columns


def test_init_db_on_existing_v1_store_adds_alerted_at_via_alter_table():
    _seed_v1_store(config.db_path())

    db.init_db()

    columns = _table_info(config.db_path())
    assert "alerted_at" in columns


def test_migration_from_v1_preserves_existing_rows():
    _seed_v1_store(config.db_path())

    db.init_db()

    with sqlite3.connect(config.db_path()) as conn:
        rows = conn.execute("SELECT id FROM jobs").fetchall()
    assert rows == [("job-1",)], "existing rows must survive the migration (never wiped)"


def test_migration_from_v1_leaves_alerted_at_null_for_existing_rows():
    _seed_v1_store(config.db_path())

    db.init_db()

    with sqlite3.connect(config.db_path()) as conn:
        value = conn.execute(
            "SELECT alerted_at FROM jobs WHERE id = ?", ("job-1",)
        ).fetchone()[0]
    assert value is None


def test_init_db_on_fresh_store_sets_schema_version_to_2():
    db.init_db()

    with sqlite3.connect(config.db_path()) as conn:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert user_version == 2
    assert user_version == db.SCHEMA_VERSION


def test_migration_from_v1_bumps_schema_version_to_2():
    _seed_v1_store(config.db_path())

    db.init_db()

    with sqlite3.connect(config.db_path()) as conn:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert user_version == 2


def test_reinit_on_already_migrated_store_is_idempotent():
    db.init_db()
    db.init_db()  # second init must not error or re-alter an already-present column

    columns = _table_info(config.db_path())
    with sqlite3.connect(config.db_path()) as conn:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert "alerted_at" in columns
    assert user_version == 2
