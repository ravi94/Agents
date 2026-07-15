"""M4 — the end-to-end pipeline orchestrator seam.

Composes the two existing stage runners — M2 discovery (`run_discovery`) and
M3 scoring/alerting (`run_scoring`) — back to back under one run id. This
module owns no store write, no LLM call, and no ntfy call of its own; it only
sequences the stages and aggregates their summaries (contracts/pipeline.md).

`PipelineSummary` is the one new type this milestone adds: an in-memory
aggregate that holds the two stage summaries as-is (never recomputed) under
the shared correlation id (data-model.md). `run_pipeline` follows in T008.
"""

from __future__ import annotations

from dataclasses import dataclass

from jobhunter import obs
from jobhunter.discovery.run import RunSummary, run_discovery
from jobhunter.llm.provider import LLMProvider
from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.scoring.run import ScoreRunSummary, run_scoring
from jobhunter.scoring.scorer import format_breakdown
from jobhunter.sources.base import JobSource


@dataclass
class PipelineSummary:
    """Aggregate outcome of one orchestrated `jobhunter run` (data-model.md).

    Composition only: `discovery`/`scoring` are the exact `RunSummary`/
    `ScoreRunSummary` objects returned by the two stages, held unchanged. Not
    persisted — built, logged, printed, and discarded. `run_id` is the shared
    process correlation id (`obs.current_run_id()`), identical to both nested
    summaries' `run_id` (`"-"` only outside a configured run).
    """

    run_id: str
    discovery: RunSummary
    scoring: ScoreRunSummary


def run_pipeline(
    sources: list[JobSource],
    profile: Profile,
    prefs: Preferences,
    *,
    dry_run: bool = False,
    rerank: bool = False,
    provider: LLMProvider | None = None,
) -> PipelineSummary:
    """Run discovery then scoring end to end and aggregate their summaries.

    Composes the two existing stage runners in order (discovery before scoring
    — filter-before-score at the pipeline level, C1) and **unconditionally**:
    scoring runs even when discovery added zero new jobs, so pre-existing
    `state='new'` jobs are still scored (C4). Mints no run id of its own —
    reads the shared one `cli.main()` already configured (C2) — and owns no
    store write, LLM call, or ntfy send: those all belong to the stages it
    calls. Raises on an aborting error rather than self-notifying; `cli.main()`
    owns the whole-run failure signal (C7). See contracts/pipeline.md.
    """
    # A single source failure is isolated *inside* run_discovery
    # (RunSummary.source_failures) — never wrap this call in a try/except or a
    # per-source loop that would defeat that inherited per-source isolation (C3).
    discovery = run_discovery(sources, profile, prefs, dry_run=dry_run)
    scoring = run_scoring(
        profile, prefs, dry_run=dry_run, rerank=rerank, provider=provider
    )
    # Composed, not recomputed: the two stage summaries are held as-is (C5).
    return PipelineSummary(
        run_id=obs.current_run_id(), discovery=discovery, scoring=scoring
    )


def format_pipeline_summary(summary: PipelineSummary) -> str:
    """Render one combined per-run summary block (contracts/cli.md).

    One block, two sub-blocks: the discovery counts (with per-source ok/failed
    breakdown) and the scoring counts (with this run's top contributor). Reads
    the nested summaries only — adds no new count of its own.
    """
    d = summary.discovery
    s = summary.scoring
    lines = [
        f"Pipeline run {summary.run_id} complete.",
        f"  discovery: fetched: {d.fetched}   new: {d.new}   "
        f"seen: {d.seen}   skipped: {d.skipped}",
    ]
    if d.attempted_sources:
        lines.append("    sources:")
        for name in d.attempted_sources:
            failure = d.source_failures.get(name)
            status = f"failed  {failure}" if failure else "ok"
            lines.append(f"      {name}  {status}")
    lines.append(
        f"  scoring:   filtered_out: {s.filtered_out}   scored: {s.scored}   "
        f"alerted: {s.alerted}   reranked: {s.reranked}"
    )
    if s.top_breakdown is not None:
        lines.append(f"    top: {s.top_job_title!r} — {format_breakdown(s.top_breakdown)}")
    return "\n".join(lines)
