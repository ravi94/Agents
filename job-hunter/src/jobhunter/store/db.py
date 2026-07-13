"""T024 [US3] — the durable SQLite job store: schema init + record CRUD.

M1 only establishes the `jobs` table (empty) so later milestones (M2–M5) can
write without redefining its shape (data-model.md §"Entity: Job Record"). The
table is created with `CREATE TABLE IF NOT EXISTS`, making :func:`init_db`
idempotent — an existing store and its rows are reused, never wiped (FR-011,
US3 scenarios 1–2). `PRAGMA user_version` records the schema version for future
migrations. `id` is the dedup/idempotency key (Constitution IV): the source id
when stable, else a `title|company|city` composite the caller supplies.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from jobhunter import config

# Bump when the `jobs` schema changes; drives PRAGMA user_version + migrations.
SCHEMA_VERSION = 2

# Full Job Record shape (data-model.md). Order is the canonical column order.
COLUMNS: tuple[str, ...] = (
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
    "alerted_at",
)

# Columns a caller may set directly. Identity, the store-managed audit
# timestamps, and `alerted_at` (write-once, stamped only by the alert step)
# are handled by the store itself, never taken verbatim from input.
_MANAGED = frozenset({"id", "first_seen", "last_seen", "updated_at", "alerted_at"})
_SETTABLE = frozenset(COLUMNS) - _MANAGED

_CREATE_TABLE = """
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
    updated_at      TEXT NOT NULL,
    alerted_at      TEXT
)
"""


def _now() -> str:
    """Current instant as an ISO-8601 string (store audit timestamp)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect(db_file: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_alerted_at(conn: sqlite3.Connection) -> None:
    """Add ``alerted_at`` to a pre-M3 (v1) store that predates it (T005).

    A fresh store already has the column from ``_CREATE_TABLE``, so this is a
    no-op there; an existing v1 store gets it added via ``ALTER TABLE``,
    leaving every other column and row untouched (data-model.md).
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "alerted_at" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN alerted_at TEXT")


def init_db(path: Path | None = None) -> Path:
    """Create the job store if absent and stamp its schema version.

    Idempotent: re-running reuses the existing store and its rows (never
    wiped). Returns the resolved path to ``jobs.db``.
    """
    config.ensure_home()
    target = path or config.db_path()
    with _connect(target) as conn:
        conn.execute(_CREATE_TABLE)
        _migrate_alerted_at(conn)
        # PRAGMA does not accept bound parameters; SCHEMA_VERSION is our int.
        conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
        conn.commit()
    return target


def upsert_job(job: dict, path: Path | None = None) -> None:
    """Insert or update a job record by ``id``.

    Store-managed fields are set here, not taken from ``job``: ``first_seen`` is
    stamped on first insert and preserved thereafter; ``last_seen`` and
    ``updated_at`` are refreshed on every write. Unset settable columns fall to
    their SQL defaults (``state`` → ``'new'``; scored/explainability fields →
    null until later milestones populate them).
    """
    if "id" not in job or not job["id"]:
        raise ValueError("job record must include a non-empty 'id'")
    unknown = set(job) - frozenset(COLUMNS)
    if unknown:
        raise ValueError(f"unknown job column(s): {', '.join(sorted(unknown))}")

    target = path or config.db_path()
    now = _now()

    # Columns the caller supplied (id + any settable fields), plus timestamps.
    provided = [c for c in COLUMNS if c in job and c in _SETTABLE]
    insert_cols = ["id", *provided, "first_seen", "last_seen", "updated_at"]
    values = [job["id"], *(job[c] for c in provided), now, now, now]

    # On id conflict, refresh the supplied columns + audit timestamps, but keep
    # the original first_seen (the record's identity persists across reruns).
    updates = ", ".join(f"{c}=excluded.{c}" for c in [*provided, "last_seen", "updated_at"])

    placeholders = ", ".join("?" for _ in insert_cols)
    sql = (
        f"INSERT INTO jobs ({', '.join(insert_cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}"
    )
    with _connect(target) as conn:
        conn.execute(sql, values)
        conn.commit()


def get_job(job_id: str, path: Path | None = None) -> dict | None:
    """Return the job record for ``job_id`` as a dict, or ``None`` if absent."""
    target = path or config.db_path()
    with _connect(target) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row is not None else None


def list_jobs_by_state(state: str, path: Path | None = None) -> list[dict]:
    """Return every job record currently in ``state``, ordered by ``id``.

    The read seam the scoring orchestrator walks over ``state='new'`` jobs
    (T014). Ordering by ``id`` keeps a run deterministic across invocations.
    """
    target = path or config.db_path()
    with _connect(target) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE state = ? ORDER BY id", (state,)
        ).fetchall()
    return [dict(row) for row in rows]


def touch_last_seen(job_id: str, path: Path | None = None) -> bool:
    """Advance ``last_seen`` to now for ``job_id``; a pure re-sighting, not a change.

    Leaves ``first_seen``, ``state``, ``updated_at``, and all content columns
    untouched — re-seeing a posting is not a content update (FR-015), so it
    must never reset a later ``state`` (e.g. ``interested``) back toward
    ``new``, nor make ``updated_at`` claim content changed when it didn't.
    Returns ``False`` (no-op) if ``job_id`` is absent.
    """
    target = path or config.db_path()
    with _connect(target) as conn:
        cursor = conn.execute(
            "UPDATE jobs SET last_seen = ? WHERE id = ?", (_now(), job_id)
        )
        conn.commit()
    return cursor.rowcount > 0
