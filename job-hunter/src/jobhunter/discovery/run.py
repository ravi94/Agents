"""T020 [US1] — the discovery orchestrator: fetch → normalize → dedup → persist.

Takes already-constructed `JobSource` instances (never resolves source names
or credentials itself — that is the CLI's job, T021) so a fixture source can
drive the whole pipeline in tests with no live call (contracts/cli.md,
research.md §9). A source raising `SourceError` is isolated: recorded in
`RunSummary.source_failures` and the run continues with the rest (FR-017).
`dry_run` still fetches/normalizes/dedups and reports real counts — only the
store write is skipped (contracts/cli.md).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from jobhunter import obs
from jobhunter.discovery.dedup import dedup_within_run
from jobhunter.discovery.normalize import normalize_adzuna, normalize_jsearch
from jobhunter.discovery.query import derive_queries
from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.sources.base import JobSource, RawPosting, SourceError
from jobhunter.store import db

# Per-source raw-posting -> canonical-Job mapping. Adding a source means
# adding one entry here — no other orchestrator change (FR-002).
NORMALIZERS: dict[str, Callable[[RawPosting], dict | None]] = {
    "jsearch": normalize_jsearch,
    "adzuna": normalize_adzuna,
}


@dataclass
class RunSummary:
    """Aggregate outcome of one discovery run (data-model.md "RunSummary")."""

    fetched: int = 0
    new: int = 0
    seen: int = 0
    skipped: int = 0
    source_failures: dict[str, str] = field(default_factory=dict)
    attempted_sources: list[str] = field(default_factory=list)
    run_id: str = ""


def run_discovery(
    sources: list[JobSource],
    profile: Profile,
    prefs: Preferences,
    *,
    dry_run: bool = False,
) -> RunSummary:
    """Run one discovery pass over `sources` and return its summary."""
    # Reuse the CLI's already-configured correlation id (obs.current_run_id())
    # so the printed summary and every log line for this run agree — a fresh
    # id here would desync them (SC-005). "-" outside a configured run (e.g.
    # library/test use) matches what the log filter would show too.
    summary = RunSummary(run_id=obs.current_run_id())
    log = obs.get_logger("discovery")

    queries = derive_queries(profile, prefs)
    if not queries:
        log.info("discover: no usable query (empty profile roles and prefs.search) — no-op")
        return summary

    db.init_db()

    normalized: list[dict] = []
    for source in sources:
        summary.attempted_sources.append(source.name)
        try:
            with obs.trace("source.fetch", source=source.name, logger=log):
                raw_postings = source.fetch(queries)
        except SourceError as exc:
            summary.source_failures[source.name] = str(exc)
            log.warning("discover: source failed source=%s reason=%s", source.name, exc)
            continue

        summary.fetched += len(raw_postings)
        normalize = NORMALIZERS.get(source.name)
        for raw in raw_postings:
            job = normalize(raw) if normalize else None
            if job is None:
                summary.skipped += 1
            else:
                normalized.append(job)

    with obs.trace("discovery.persist", logger=log):
        for job in dedup_within_run(normalized):
            # dedup_key is a pipeline-internal cross-source match key, not a
            # persisted Job column (data-model.md) — drop it before storing.
            job = {k: v for k, v in job.items() if k != "dedup_key"}
            existing = db.get_job(job["id"])
            if existing is not None:
                summary.seen += 1
                if not dry_run:
                    db.touch_last_seen(job["id"])
            else:
                summary.new += 1
                if not dry_run:
                    db.upsert_job(job)

    log.info(
        "discover: run complete run_id=%s fetched=%d new=%d seen=%d skipped=%d failures=%d",
        summary.run_id,
        summary.fetched,
        summary.new,
        summary.seen,
        summary.skipped,
        len(summary.source_failures),
    )
    return summary
