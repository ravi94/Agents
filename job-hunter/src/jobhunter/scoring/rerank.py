"""T034/T036 [US4] — the optional bounded re-rank pass.

Given this run's newly-scored jobs, sends at most the top ~25 (by `score`)
through a single bounded `LLMProvider.rerank` call and writes each returned
reason onto that job's row — mirroring `scoring/alert.py`'s `run_alerts`
shape. Never a precondition for filtering, scoring, or alerting: a provider
failure/timeout here is caught, logged, and leaves every already-persisted
score/breakdown/alert untouched (contracts/cli.md's re-rank-failure rule).
"""

from __future__ import annotations

from pathlib import Path

from jobhunter import obs
from jobhunter.llm.provider import LLMProvider
from jobhunter.models.profile import Profile
from jobhunter.store import db

_RERANK_CAP = 25

# Only these fields ever cross the provider boundary — never prefs.yaml
# content or tracking state like score/state/alerted_at (Constitution I).
_CANDIDATE_FIELDS = ("id", "title", "description", "matched_skills")


def run_rerank(
    jobs: list[dict],
    profile: Profile,
    provider: LLMProvider,
    *,
    path: Path | None = None,
    dry_run: bool = False,
) -> int:
    """Re-rank the top ~25 of `jobs` by `score`; return how many got a reason.

    Calls `provider.rerank(candidates, profile)` exactly once, regardless of
    how many `jobs` are passed in. Any provider exception is caught and
    logged here — it must never propagate out and never touch a persisted
    score/breakdown/alert. `dry_run` still calls the provider (so the
    returned count reflects what *would* happen) but writes nothing.
    """
    ranked = sorted(jobs, key=lambda job: job.get("score") or 0.0, reverse=True)
    top = ranked[:_RERANK_CAP]
    if not top:
        return 0

    candidates = [{field: job.get(field) for field in _CANDIDATE_FIELDS} for job in top]

    log = obs.get_logger("scoring")
    try:
        with obs.trace("scoring.rerank", source=f"candidates={len(candidates)}", logger=log):
            reasons = provider.rerank(candidates, profile)
    except Exception as exc:  # noqa: BLE001 — never breaks the run
        log.warning(
            "scoring.rerank: provider failed (%s); leaving reasons unset", type(exc).__name__
        )
        return 0

    annotated = 0
    for job in top:
        reason = reasons.get(job["id"])
        if reason is None:
            continue
        annotated += 1
        if not dry_run:
            db.upsert_job({**job, "reason": reason}, path=path)

    return annotated
