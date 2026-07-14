"""T025 [US3] — the alert step: notify once on genuinely new, high-scoring jobs.

Given this run's newly-scored jobs, sends at most `prefs.alerting.
max_alerts_per_run` ntfy notifications for jobs at/above `alerting.
score_threshold` whose `alerted_at` is still `NULL`, then write-once stamps
`alerted_at` via `store.db.mark_alerted` — the mechanism that guarantees at
most one notification per job, ever (FR-009, data-model.md).
"""

from __future__ import annotations

from pathlib import Path

from jobhunter import obs
from jobhunter.models.preferences import Preferences
from jobhunter.store import db


def run_alerts(
    jobs: list[dict],
    prefs: Preferences,
    *,
    path: Path | None = None,
    dry_run: bool = False,
) -> int:
    """Notify on qualifying jobs from `jobs`; return how many were alerted.

    A job qualifies iff its `alerted_at` is `None`, it has a `score`, and that
    score is at/above `prefs.alerting.score_threshold`. Processes `jobs` in
    the given order and stops once `max_alerts_per_run` notifications have
    been sent this call — jobs beyond the cap are left untouched. `dry_run`
    reports the same count but sends no notification and stamps nothing
    (contracts/cli.md `--dry-run`: "write nothing").
    """
    alerted = 0
    for job in jobs:
        if alerted >= prefs.alerting.max_alerts_per_run:
            break
        if job.get("alerted_at") is not None:
            continue
        score = job.get("score")
        if score is None or score < prefs.alerting.score_threshold:
            continue

        if not dry_run:
            # Metadata only: the job id is the trace source, never the title
            # or notification text (Constitution VIII).
            with obs.trace("scoring.alert", source=job["id"]):
                title = job.get("title") or job["id"]
                obs.notify(f"New match: {title} (score {score:.2f})")
                db.mark_alerted(job["id"], path=path)
        alerted += 1

    return alerted
