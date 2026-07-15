# Implementation Plan: End-to-End Pipeline Orchestrator

**Branch**: `004-orchestrator-run` | **Date**: 2026-07-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-orchestrator-run/spec.md`

## Summary

M4 collapses the two manual commands the user runs today — `jobhunter discover`
(M2: discover → normalize → dedup → persist) and `jobhunter score` (M3:
filter → score → persist → alert) — into a single `jobhunter run` command that
executes the whole pipeline end to end in one invocation, under one run
identity, ending with one combined summary. It is deliberately a **composition
layer, not new pipeline logic**: it reuses `discovery.run.run_discovery` and
`scoring.run.run_scoring` verbatim, in that order, so filter-before-score,
per-source isolation, the never-re-alert guarantee, and bounded LLM usage are
all inherited rather than re-implemented.

Technical approach: a new `pipeline/` package with `run.py` exposing
`run_pipeline(...) -> PipelineSummary` and a `PipelineSummary` dataclass that
holds the existing `RunSummary` (discovery) and `ScoreRunSummary` (scoring)
side by side under the shared `run_id`; plus a `jobhunter run` CLI command with
`--source` (repeatable, mirrors `discover`), `--dry-run`, and `--rerank`
(passed straight through to scoring). Three of the spec's observability
requirements are **already satisfied by existing infrastructure** and the plan
verifies rather than rebuilds them: the single correlation id (`main()` mints
it once via `obs.configure_run_logging()`; both stage runners already reuse
`obs.current_run_id()`), the per-call tracing (each source and the re-rank call
already trace themselves), and the whole-run-failure ntfy (`main()` already
routes `CommandError`/unexpected exceptions to `obs.notify_error`). The genuinely
new work is the composition seam, the combined summary shape + its printed
rendering, and the CLI wiring — all thin, all deterministic, all TDD-tested.

## Technical Context

**Language/Version**: Python 3.11+ (matches M1/M2/M3).

**Primary Dependencies**: No new dependencies. Reuses `discovery.run.run_discovery`
and `scoring.run.run_scoring` as-is; the source registry (`JSearchSource`,
`AdzunaSource`) and provider seam (`ClaudeCLIProvider`, constructed only when
`--rerank` is passed) are the same ones the `discover`/`score` handlers already
build. `obs` (run id, tracing, ntfy), `config` (profile/prefs paths), pydantic
loaders — all reused. No web framework (FastAPI is M5).

**Storage**: The existing M1/M2/M3 SQLite store (`jobs.db`). **No schema change** —
the orchestrator only drives the existing stages, which own all writes. Schema
stays at version 2.

**Testing**: `pytest`. TDD is mandatory (Constitution VII). The composition seam
is deterministic and tested directly by stubbing/faking the two stage runners
(assert order = discovery-before-scoring, that a discovery failure does not
prevent scoring, that `--dry-run`/`--rerank`/`--source` propagate correctly, and
that the combined summary aggregates both stage summaries). One integration test
drives the real `run_pipeline` over fixture sources + fixture store with the LLM
and any network mocked — no live JSearch/Adzuna/Ollama/Claude call is a pass
condition. CLI exit-code/error tests mirror the existing `test_cli_score.py`.

**Target Platform**: Local macOS (single-user), CLI-invoked, **manual trigger
only** — no scheduler this milestone (Constitution Scheduling constraint;
launchd is a later fast-follow).

**Project Type**: Single Python project (CLI + library), extending the M1–M3
package. No frontend.

**Performance Goals**: Not latency-sensitive. One run = one discovery pass
(bounded by free-tier query budget) followed by scoring over the resulting
`state='new'` jobs (low hundreds at most). The orchestrator adds no per-job work
of its own beyond aggregating two summaries.

**Constraints**: Filter-before-score is preserved by ordering (discovery →
scoring, and scoring itself gates before scoring). A single dead discovery source
must not abort the run (inherited from `run_discovery`'s per-source try/except;
the orchestrator must not wrap the discovery call in a way that defeats it).
Idempotent monitor semantics and the at-most-once alert guarantee are inherited
from M2/M3 and must not be weakened by composing them. `--dry-run` must produce
zero writes and zero notifications across *both* stages.

**Scale/Scope**: Single user, one SQLite store, one orchestrated run per manual
invocation. Scheduling, and the FastAPI triage/tracker board, are explicitly out
of scope (later milestones).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|---|---|---|
| I. Explicit LLM Provider Boundaries | The orchestrator adds no new LLM touchpoint. The only text-generation call in the composed pipeline is M3's optional `--rerank`, reached through the existing `LLMProvider` seam and constructed only when the flag is passed. No `prefs.yaml`/profile/tracking payload crosses any boundary that didn't already. | PASS |
| II. Bounded Usage, Zero Incremental Cost | No new or unbounded usage introduced. `--rerank` stays opt-in and capped at ~25 survivors / one call per run (M3's cap, unchanged). Discovery stays on free tiers. Zero incremental spend. | PASS |
| III. Ethical Boundaries (NON-NEGOTIABLE) | No auto-apply; no new sources or scraping — the orchestrator only sequences existing read/score/alert stages. Aggregator rate-limit/backoff behavior is inherited from M2 sources, unchanged. | PASS (N/A) |
| IV. Monitor, Not Search (Idempotent State) | Idempotency and never-re-alert are properties of the composed stages: dedup keys and `last_seen` (M2), `alerted_at` write-once (M3). Composing them in one run cannot re-alert a seen role — the plan adds a test that two consecutive `run`s alert an above-threshold role exactly once total (SC-005). | PASS |
| V. Explainable Ranking | Unchanged — scoring still persists the full breakdown; the orchestrator surfaces (does not replace) M3's summary, including this run's top contributor. No opaque number introduced. | PASS |
| VI. Deterministic Simplicity (YAGNI) | The seam is a plain, branch-free deterministic sequence of two existing function calls plus summary aggregation. No agent framework, no scheduler, no new service. This is the minimal composition — nothing speculative added. | PASS |
| VII. Test-First Development (NON-NEGOTIABLE) | The composition order, failure-isolation propagation, flag pass-through, and summary aggregation are deterministic and tested first (stage runners stubbed). The one integration test mocks all network/LLM; no live call gates a test. | PASS |
| VIII. Observable by Default | The whole point of the milestone. Single run id: already minted once in `main()` and reused by both stages — verified, not rebuilt. Per-call tracing: inherited (each source + the re-rank call already trace). New: a combined end-of-run summary log line (per-source discovered/new/deduped + filtered_out/scored/alerted) and its printed rendering; whole-run-failure ntfy already routed by `main()`. | PASS |

**Technology & Operational Constraints**: No new dependency, no schema change,
no new store. **Filter before score** is the literal ordering of the two composed
stages. **Resilience** (one dead source never fails the run) is inherited from
`run_discovery` and asserted by the plan's tests. **Scheduling** stays manual —
this milestone explicitly does **not** add launchd/cron.

**Result**: PASS — no violations. Complexity Tracking not required.

**Post-design re-check (after Phase 1)**: The data model adds one in-memory
aggregate (`PipelineSummary`) composed from the two existing stage summaries and
introduces **no persisted field and no schema change**. The `run` CLI command
reuses the existing flags/loaders. Re-check result: **PASS** — the design stays a
thin composition layer, consistent with Principle VI.

## Project Structure

### Documentation (this feature)

```text
specs/004-orchestrator-run/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── cli.md           # `jobhunter run` command surface (flags, output, exit codes)
│   └── pipeline.md      # run_pipeline(...) -> PipelineSummary composition contract
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created here)
```

### Source Code (repository root)

```text
src/jobhunter/
├── pipeline/                 # NEW package — the orchestration seam
│   ├── __init__.py
│   └── run.py                # run_pipeline(...) -> PipelineSummary; composes
│                             #   discovery.run.run_discovery then
│                             #   scoring.run.run_scoring under the shared run_id
├── discovery/
│   └── run.py                # REUSED as-is (run_discovery, RunSummary)
├── scoring/
│   └── run.py                # REUSED as-is (run_scoring, ScoreRunSummary)
├── sources/                  # REUSED (JSearchSource, AdzunaSource registry)
├── obs.py                    # REUSED (run id, trace, notify_error) — no change
└── cli.py                    # EDITED — add `run` subcommand + _run_handler,
                              #   combined-summary rendering

tests/
├── unit/
│   ├── test_pipeline_run.py  # NEW — composition order, failure isolation,
│   │                         #   flag pass-through, summary aggregation (stubs)
│   └── test_cli_run.py       # NEW — `run` flags, exit codes, error paths
└── integration/
    └── test_run_end_to_end.py# NEW — real run_pipeline over fixture sources +
                              #   fixture store; network/LLM mocked
```

**Structure Decision**: Single Python project, extending the existing
`src/jobhunter/` package. A new `pipeline/` package (mirroring the `discovery/`
and `scoring/` package/`run.py` shape already established) holds the one new
module; `cli.py` gains one subcommand. No other production file changes, and no
schema/store change. This keeps the orchestrator a clearly-bounded composition
layer over the M2/M3 stages rather than diffusing run logic across them.

## Complexity Tracking

> No Constitution Check violations. This section intentionally left empty — the
> milestone is a minimal composition layer that adds no dependency, no schema
> change, no new service, and no speculative abstraction.
