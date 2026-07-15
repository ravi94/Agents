# Phase 0 Research: End-to-End Pipeline Orchestrator

No `[NEEDS CLARIFICATION]` markers survived the spec; the feature is a
composition of two already-built, already-tested stages. This document records
the design decisions the composition seam still has to make, each grounded in the
existing M2/M3 code and the constitution.

## 1. Where the orchestrator lives

- **Decision**: A new `src/jobhunter/pipeline/` package with `run.py` exposing
  `run_pipeline(...) -> PipelineSummary`, mirroring the existing
  `discovery/run.py` (`run_discovery` → `RunSummary`) and `scoring/run.py`
  (`run_scoring` → `ScoreRunSummary`) shape.
- **Rationale**: The two composed stages already follow a `<stage>/run.py`
  convention; a peer `pipeline/run.py` is the least-surprising home and keeps the
  seam a first-class, testable module rather than logic buried in `cli.py`.
- **Alternatives considered**: (a) Put the composition directly in a `cli.py`
  handler — rejected: it would make the orchestration untestable without going
  through argparse and would mix rendering with sequencing. (b) A single
  top-level `orchestrator.py` — rejected: inconsistent with the established
  per-stage package layout.

## 2. The combined summary shape

- **Decision**: `PipelineSummary` is a thin dataclass holding the two existing
  stage summaries plus the shared run id:
  `PipelineSummary(run_id, discovery: RunSummary, scoring: ScoreRunSummary)`.
  Rendering composes both stages' existing printed forms into one block.
- **Rationale**: Reuse over re-derivation (Constitution VI). `RunSummary` already
  carries per-source discovered/new/deduped counts and `source_failures`;
  `ScoreRunSummary` already carries `filtered_out`/`scored`/`alerted`/`reranked`
  and this-run's top contributor. Wrapping them keeps every field the spec's
  end-of-run summary (FR-010) needs without flattening or duplicating them.
- **Alternatives considered**: A flat summary that copies each field up —
  rejected: duplicates the two stage contracts and would drift when either
  stage's summary evolves.

## 3. Reusing the single correlation id (FR-007)

- **Decision**: The orchestrator does **not** mint a run id. `cli.main()` already
  calls `obs.configure_run_logging()` once per process, and both `run_discovery`
  and `run_scoring` already reuse `obs.current_run_id()`. `run_pipeline` calls
  both within that one configured run, and stamps the same
  `obs.current_run_id()` onto `PipelineSummary.run_id`.
- **Rationale**: A fresh id inside the orchestrator would desync the two stages'
  log lines from each other and from the printed summary — the exact failure M2
  already guards against in `run_discovery`'s comment. Reusing the process run id
  makes the whole run reconstructable from one id end to end (SC-003), with zero
  new observability code.
- **Alternatives considered**: Minting a pipeline-level id and threading it into
  both stages — rejected: redundant with the existing process-level id and would
  require changing the two stage signatures for no gain.

## 4. Per-source failure isolation (FR-004) — inherited, not rebuilt

- **Decision**: The orchestrator calls `run_discovery(sources, ...)` once with the
  full source list and lets it isolate per-source failures internally (its
  existing try/except populating `RunSummary.source_failures`). The orchestrator
  must **not** loop sources itself or wrap the call so an exception escapes.
- **Rationale**: `run_discovery` already delivers "one dead source never fails the
  run; partial results are valid." Re-implementing isolation at the orchestrator
  level would duplicate and risk diverging from that guarantee.
- **Alternatives considered**: Orchestrator-level per-source looping — rejected as
  redundant duplication of M2 behavior.

## 5. Scoring still runs when discovery adds nothing / all sources fail (FR-004, edge case)

- **Decision**: `run_scoring` is called unconditionally after `run_discovery`,
  regardless of how many jobs discovery added or how many sources failed. Scoring
  operates over whatever `state='new'` jobs are in the store (this run's finds
  plus prior unscored leftovers), matching M3's existing behavior.
- **Rationale**: "Partial results are valid results." Even a total discovery
  outage should still score any pre-existing unscored inventory. This falls out
  naturally from calling the two stages in sequence with no conditional guard.
- **Alternatives considered**: Skip scoring when discovery found zero new jobs —
  rejected: it would strand pre-existing unscored jobs and contradicts the spec's
  edge case.

## 6. Whole-run failure ntfy (FR-011) — inherited from `main()`

- **Decision**: The orchestrator surfaces an aborting error by *raising*
  (`CommandError` for actionable failures such as missing profile/prefs, or any
  unexpected exception). `cli.main()` already catches both and routes them to
  `obs.notify_error`. The orchestrator adds no ntfy call of its own for run
  failure.
- **Rationale**: The error-notification path already exists and is uniform across
  every command; a bespoke ntfy in the orchestrator would double-send or diverge.
  Per-role *alerts* remain the scoring stage's job (unchanged).
- **Alternatives considered**: An orchestrator-owned failure ntfy — rejected:
  duplicates `main()`'s existing handler.

## 7. Flag surface for `run`

- **Decision**: `jobhunter run [--source NAME]... [--dry-run] [--rerank]`.
  `--source` (repeatable) mirrors `discover` and is passed to the discovery stage;
  `--dry-run` is passed to **both** stages; `--rerank` is passed to scoring
  (constructing `ClaudeCLIProvider` only when set, exactly as `_score_handler`
  does today).
- **Rationale**: Reuses the exact flag semantics users already know from
  `discover`/`score`, so `run` is their union with no new concepts. `--dry-run`
  propagating to both stages is what makes the rehearsal guarantee (FR-012) hold
  end to end.
- **Alternatives considered**: A no-flags `run` that always uses all sources and
  never reranks — rejected: it would make `run` strictly less capable than the two
  commands it replaces, pushing users back to the separate commands.

## Summary of decisions

| # | Decision |
|---|---|
| 1 | New `pipeline/run.py` package, peer to `discovery/`/`scoring/` |
| 2 | `PipelineSummary` wraps the two existing stage summaries + `run_id` |
| 3 | Reuse the process-level `obs.current_run_id()`; do not mint a new id |
| 4 | Call `run_discovery` once; inherit its per-source isolation |
| 5 | Call `run_scoring` unconditionally after discovery |
| 6 | Raise on whole-run failure; let `main()`'s existing handler ntfy |
| 7 | `run` flags = union of `discover` + `score` (`--source`/`--dry-run`/`--rerank`) |
