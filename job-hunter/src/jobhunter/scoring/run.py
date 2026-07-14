"""T014 [US1] — the scoring orchestrator: filter → score → persist.

Walks every `state='new'` job in the store: a job failing any hard filter is
persisted as `state='filtered_out'` with a `reason` naming the violated
dimensions and no score; a survivor is scored against the profile/prefs and
persisted as `state='scored'` with its `score`, JSON `breakdown`, and JSON
`matched_skills` (data-model.md's atomicity rule — score and breakdown are
written together, never one without the other). Mirrors M2's `run_discovery`:
takes already-constructed `Profile`/`Preferences` (never resolves them itself)
so fixtures drive the whole pipeline with no live call, and `dry_run` computes
the same counts but skips every store write (contracts/cli.md).

After scoring, this run's newly-scored jobs (in-memory, not a fresh store
query) are handed to `scoring.alert.run_alerts` (T025/T027): a job already
`alerted_at`-set from a prior run is never revisited, since a rescoring run
only ever processes `state='new'` jobs, so an already-`scored` job simply
never reaches this loop again (data-model.md's write-once `alerted_at`
guarantee, FR-009). `reranked` stays `0` here — the optional re-rank (US4)
extends this orchestrator later without changing the filter/score/alert core.
"""

from __future__ import annotations

from dataclasses import dataclass

from jobhunter import obs
from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.scoring.alert import run_alerts
from jobhunter.scoring.filters import apply_filters
from jobhunter.scoring.scorer import ScoreBreakdown, score_job, to_job_fields
from jobhunter.store import db


@dataclass
class ScoreRunSummary:
    """Aggregate outcome of one scoring run (data-model.md "ScoreRunSummary").

    `top_job_title`/`top_breakdown` name this run's highest-`overall`-scoring
    job so the CLI can surface its top contributing factor without a separate
    query (SC-004) — `None` when nothing was scored this run.
    """

    filtered_out: int = 0
    scored: int = 0
    alerted: int = 0
    reranked: int = 0
    run_id: str = ""
    top_job_title: str | None = None
    top_breakdown: ScoreBreakdown | None = None


def run_scoring(
    profile: Profile,
    prefs: Preferences,
    *,
    dry_run: bool = False,
) -> ScoreRunSummary:
    """Filter and score every `state='new'` job; return the run summary."""
    # Reuse the CLI's correlation id (as run_discovery does) so the printed
    # summary and every log line for this run agree.
    summary = ScoreRunSummary(run_id=obs.current_run_id())
    log = obs.get_logger("scoring")

    db.init_db()

    newly_scored: list[dict] = []
    with obs.trace("scoring.persist", logger=log):
        for job in db.list_jobs_by_state("new"):
            result = apply_filters(job, prefs)
            if not result.passed:
                summary.filtered_out += 1
                if not dry_run:
                    reason = "failed filters: " + ", ".join(result.failed_filters)
                    db.upsert_job({**job, "state": "filtered_out", "reason": reason})
                continue

            # Score and breakdown are computed and persisted together — a scored
            # row never carries a null breakdown (data-model.md atomicity rule).
            score_result = score_job(job, profile, prefs)
            summary.scored += 1
            if (
                summary.top_breakdown is None
                or score_result.breakdown.overall > summary.top_breakdown.overall
            ):
                summary.top_job_title = job.get("title") or job["id"]
                summary.top_breakdown = score_result.breakdown
            scored_job = {**job, "state": "scored", **to_job_fields(score_result)}
            newly_scored.append(scored_job)
            if not dry_run:
                db.upsert_job(scored_job)

    if newly_scored:
        summary.alerted = run_alerts(newly_scored, prefs, dry_run=dry_run)

    log.info(
        "score: run complete run_id=%s filtered_out=%d scored=%d alerted=%d reranked=%d",
        summary.run_id,
        summary.filtered_out,
        summary.scored,
        summary.alerted,
        summary.reranked,
    )
    return summary
