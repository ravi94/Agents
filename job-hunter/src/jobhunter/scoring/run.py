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

`alerted`/`reranked` stay `0` here — the alert step (US3) and optional re-rank
(US4) extend this orchestrator later without changing the filter/score core.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from jobhunter import obs
from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.scoring.filters import apply_filters
from jobhunter.scoring.scorer import score_job
from jobhunter.store import db


@dataclass
class ScoreRunSummary:
    """Aggregate outcome of one scoring run (data-model.md "ScoreRunSummary")."""

    filtered_out: int = 0
    scored: int = 0
    alerted: int = 0
    reranked: int = 0
    run_id: str = ""


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
            if not dry_run:
                db.upsert_job(
                    {
                        **job,
                        "state": "scored",
                        "score": score_result.breakdown.overall,
                        "breakdown": score_result.breakdown.model_dump_json(),
                        "matched_skills": json.dumps(score_result.matched_skills),
                    }
                )

    log.info(
        "score: run complete run_id=%s filtered_out=%d scored=%d alerted=%d reranked=%d",
        summary.run_id,
        summary.filtered_out,
        summary.scored,
        summary.alerted,
        summary.reranked,
    )
    return summary
