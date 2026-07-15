---
description: "Task list for End-to-End Pipeline Orchestrator (M4)"
---

# Tasks: End-to-End Pipeline Orchestrator

**Input**: Design documents from `/specs/004-orchestrator-run/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Test-First Development is NON-NEGOTIABLE (Constitution VII). Every task implementing new behavior is preceded by a test written first and observed to fail. The composition seam is tested by **stubbing/faking the two stage runners** (`run_discovery`, `run_scoring`) and by one integration test over **fake sources + a fixture store with all network/LLM mocked** — never a live JSearch/Adzuna/Ollama/Claude call, and never exact wording as a pass condition.

**Organization**: Grouped by user story so each story is independently implementable and testable. This milestone is a **composition layer**: it reuses the M2 discovery stage (`discovery/run.py`) and the M3 scoring/alerting stage (`scoring/run.py`) verbatim and adds only the orchestration seam + the `run` CLI command. Several spec guarantees (single run id, per-call tracing, whole-run-failure ntfy, per-source isolation, dry-run) are **inherited** from existing infrastructure; the tasks that cover them are predominantly test-hardening of that inherited behavior plus small additions — mirroring how M3's US2 hardened US1's scorer.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 / US4 (maps to spec.md user stories)
- Paths are relative to repository root; single Python project per [plan.md](./plan.md).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package scaffolding and shared test doubles for the orchestration seam. No new runtime dependency and no schema change this milestone.

- [X] T001 [P] Create the new package skeleton: `src/jobhunter/pipeline/__init__.py`.
- [X] T002 [P] Add (or reuse from M2) a fake `JobSource` test helper under `tests/fixtures/` — one that returns a small set of fixture jobs and one that raises on fetch — so the pipeline integration tests can exercise the discover→score path and the per-source failure path without live network.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The one shared in-memory aggregate every story's summary composes. No user story work can begin until it exists.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 [P] Unit test `PipelineSummary` shape in `tests/unit/test_pipeline_run.py`: holds `run_id` + `discovery` (`RunSummary`) + `scoring` (`ScoreRunSummary`); `run_id` equals both nested summaries' `run_id`; fields are composed, not recomputed ([data-model.md](./data-model.md)) — write first, confirm failing.
- [X] T004 Implement the `PipelineSummary` dataclass in `src/jobhunter/pipeline/run.py` per [data-model.md](./data-model.md) — satisfies T003.

**Checkpoint**: The combined-summary aggregate exists; user stories can now begin.

---

## Phase 3: User Story 1 — One command runs the whole pipeline (Priority: P1) 🎯 MVP

**Goal**: A single `jobhunter run` executes discover → normalize → dedup → persist (M2) then filter → score → persist → alert (M3) end to end in one invocation, under one run id, printing one combined summary.

**Independent Test**: With fake sources and a fixture store (network/LLM mocked), invoke `run_pipeline` (and the `run` command): jobs are discovered and persisted, then the newly-added jobs are filtered/scored, an above-threshold new job alerts once, and one combined summary is returned — with no intermediate manual step.

### Tests for User Story 1 (write first, confirm failing) ⚠️

- [X] T005 [P] [US1] Unit test composition order + unconditional scoring in `tests/unit/test_pipeline_run.py`: with `run_discovery`/`run_scoring` stubbed, `run_pipeline` calls discovery **before** scoring, and calls scoring **even when discovery returns zero new jobs** ([contracts/pipeline.md](./contracts/pipeline.md) C1, C4).
- [X] T006 [P] [US1] Unit test argument/flag pass-through in `tests/unit/test_pipeline_run.py`: `sources` reach `run_discovery`; `rerank`/`provider` reach `run_scoring`; both stages receive the same `profile`/`prefs` (C1).
- [X] T007 [P] [US1] Integration test the end-to-end run in `tests/integration/test_run_end_to_end.py` using the fake sources + fixture store (network/LLM mocked): new jobs are discovered and persisted, then filtered/scored; an above-threshold new job alerts exactly once; `run_pipeline` returns a `PipelineSummary` aggregating both stages.

### Implementation for User Story 1

- [X] T008 [US1] Implement `run_pipeline(sources, profile, prefs, *, dry_run=False, rerank=False, provider=None) -> PipelineSummary` in `src/jobhunter/pipeline/run.py`: call `run_discovery` then `run_scoring` **unconditionally** in that order, reading `obs.current_run_id()` (mint nothing), and assemble `PipelineSummary` from the two returned summaries — depends on T004; satisfies T005, T006 ([contracts/pipeline.md](./contracts/pipeline.md)).
- [X] T009 [US1] Implement the combined-summary rendering helper (e.g. `format_pipeline_summary`) in `src/jobhunter/pipeline/run.py`: one block with the discovery counts (per-source ok/failed + fetched/new/seen/skipped) and the scoring counts (filtered_out/scored/alerted/reranked + top contributor), per [contracts/cli.md](./contracts/cli.md).
- [X] T010 [US1] Wire the `run` command in `src/jobhunter/cli.py`: `run [--source NAME]... [--dry-run] [--rerank]` — reuse the existing profile/prefs preconditions and source registry from `_discover_handler`, construct `ClaudeCLIProvider` only when `--rerank` is passed (as `_score_handler` does), call `run_pipeline`, and print the combined summary to stdout — satisfies T007.

**Checkpoint**: `jobhunter run` runs the whole pipeline from one command (MVP).

---

## Phase 4: User Story 2 — One dead source never kills the run (Priority: P2)

**Goal**: A single discovery source failing is isolated and recorded; the healthy sources' jobs still flow through to scoring and the run completes successfully.

**Independent Test**: Configure two fake sources where one raises; the failing source is recorded in `discovery.source_failures`, the healthy source's jobs are discovered, deduped, filtered, and scored, and the run returns success without raising.

### Tests for User Story 2 (write first, confirm failing) ⚠️

- [X] T011 [P] [US2] Unit test failure-isolation propagation in `tests/unit/test_pipeline_run.py`: given `run_discovery` returns a summary carrying a `source_failures` entry, `run_pipeline` still invokes `run_scoring` and returns normally without raising ([contracts/pipeline.md](./contracts/pipeline.md) C3, C4).
- [X] T012 [P] [US2] Integration test the partial-result path in `tests/integration/test_run_end_to_end.py`: two fake sources, one raising — the healthy source's jobs complete the full pipeline through scoring, the failure appears in `discovery.source_failures`, and the run returns success; every source failing still runs scoring over pre-existing `state='new'` jobs.

### Implementation for User Story 2

- [X] T013 [US2] Ensure `run_pipeline` calls `run_discovery` once with the full source list and does **not** wrap it in a try/except (or per-source loop) that would defeat the stage's inherited per-source isolation — a guard + comment in `src/jobhunter/pipeline/run.py` — satisfies T011.

**Checkpoint**: Partial results survive a dead source; US1 + US2 work together.

---

## Phase 5: User Story 3 — A run I can see into and be warned about (Priority: P3)

**Goal**: One correlation id ties the whole run together, an end-of-run summary states what happened, calls are traced metadata-only, and a whole-run failure reaches the user via ntfy.

**Independent Test**: A run's log lines all share one id; each external call is traced with outcome/duration and no personal payload; the end-of-run summary reports both stages' counts; a forced whole-run failure fires an error notification.

### Tests for User Story 3 (write first, confirm failing) ⚠️

- [X] T014 [P] [US3] Unit test run-id reuse in `tests/unit/test_pipeline_run.py`: `PipelineSummary.run_id == obs.current_run_id()` and equals both nested summaries' `run_id`; `run_pipeline` mints no new id ([contracts/pipeline.md](./contracts/pipeline.md) C2).
- [X] T015 [P] [US3] Unit test the combined end-of-run summary log line in `tests/unit/test_pipeline_run.py`: `run_pipeline` emits one summary log line carrying both stages' headline counts under the run id, and logs **counts/metadata only** — never resume/prefs/profile/job payload (C6, Constitution VIII).
- [X] T016 [P] [US3] Unit test whole-run-failure notification at the CLI seam in `tests/unit/test_cli_run.py`: a `run` that raises (e.g. missing profile/prefs, or a stage error) routes to `obs.notify_error` and exits non-zero, and `run_pipeline` itself raises rather than self-notifying (C7).

### Implementation for User Story 3

- [X] T017 [US3] Add the combined end-of-run summary log line to `src/jobhunter/pipeline/run.py` via `obs.get_logger` (counts/metadata only) — satisfies T015. Confirm (no new code expected) that the shared run id and per-call tracing are inherited: `cli.main()` already mints the id via `obs.configure_run_logging()` and both stages already trace their own calls — satisfies T014.

**Checkpoint**: The run is observable end to end and fails loudly; US1–US3 all functional.

---

## Phase 6: User Story 4 — Rehearse a run without touching anything (Priority: P4)

**Goal**: `jobhunter run --dry-run` exercises the full pipeline with zero store writes and zero notifications, while still reporting the counts the run would have produced.

**Independent Test**: `run_pipeline(dry_run=True)` over a fixture store leaves it byte-for-byte unchanged and sends nothing, yet the combined summary still reports would-be counts.

### Tests for User Story 4 (write first, confirm failing) ⚠️

- [X] T018 [P] [US4] Unit test dry-run propagation in `tests/unit/test_pipeline_run.py`: `dry_run=True` reaches **both** `run_discovery` and `run_scoring` ([contracts/pipeline.md](./contracts/pipeline.md) C8).
- [X] T019 [P] [US4] Integration test rehearsal purity in `tests/integration/test_run_end_to_end.py`: `run_pipeline(dry_run=True)` over a seeded fixture store leaves it unchanged (no new jobs, no state transitions, no `alerted_at` stamps) and sends no notification, while the combined summary still reports the would-be counts (SC-007).

### Implementation for User Story 4

- [X] T020 [US4] Add a dry-run annotation to the combined-summary rendering (e.g. a `(dry run — no writes, no alerts)` note) in `src/jobhunter/pipeline/run.py` and/or `src/jobhunter/cli.py` per [contracts/cli.md](./contracts/cli.md) — depends on T009, T010; satisfies the rehearsal UX in T019.

**Checkpoint**: All four user stories independently functional; `--dry-run` is a safe rehearsal.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validation and finishing touches spanning stories.

- [ ] T021 [P] Update `README.md`: the `jobhunter run` command and its `--source`/`--dry-run`/`--rerank` flags, noting it composes `discover` + `score` with no schema change and no scheduler (manual trigger only). Keep the run/setup steps current.
- [ ] T022 [P] Add CLI error/exit-code tests for `run` in `tests/unit/test_cli_run.py`: missing profile/prefs errors non-zero; an unknown `--source` errors; a clean no-op run (nothing to discover, nothing new to score) exits `0` (per [contracts/cli.md](./contracts/cli.md)).
- [ ] T023 Run the [quickstart.md](./quickstart.md) validation end-to-end (fake sources; Ollama and `--rerank` both optional) and confirm SC-001…SC-007 are met; fix any gaps.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup — **blocks all user stories** (the `PipelineSummary` aggregate).
- **User Stories (Phase 3–6)**: each depends on Foundational. US1 is the MVP and builds the seam (`run_pipeline`) + the `run` CLI command that US2–US4 then harden/extend. US2 (isolation), US3 (observability), and US4 (dry-run) predominantly prove inherited guarantees and add small increments on top of US1's `run_pipeline`/`cli.py`, so within one developer they proceed in priority order P1 → P2 → P3 → P4.
- **Polish (Phase 7)**: depends on the user stories being delivered.

### User Story Dependencies

- **US1 (P1)**: after Phase 2. The foundational MVP slice (compose the two stages + `run` command).
- **US2 (P2)**: after US1 — its tests and guard target the same `run_pipeline`; not safe to parallelize with US1 (shared file).
- **US3 (P3)**: after US1 — adds the combined summary log line to the same `run_pipeline` and a CLI-seam ntfy test; shares `pipeline/run.py`/`cli.py`.
- **US4 (P4)**: after US1 — adds dry-run purity tests + a rendering annotation to the same shared files.

### Within Each User Story

- Tests written and observed to FAIL before implementation (Constitution VII).
- `PipelineSummary` (Foundational) before `run_pipeline`; `run_pipeline` before the `run` CLI wiring; CLI wiring before the rendering/observability increments.

### Parallel Opportunities

- Setup: T001, T002 in parallel.
- US1: test tasks T005–T007 in parallel (T005/T006 stub the stage runners; T007 is the integration test — different concerns, and T007 lives in a different file).
- US2: T011 (unit) and T012 (integration) in parallel — different files.
- US3: T014–T016 in parallel — T014/T015 in `test_pipeline_run.py`, T016 in `test_cli_run.py`.
- US4: T018 (unit) and T019 (integration) in parallel — different files.
- Polish: T021 (README) and T022 (CLI tests) in parallel.
- **Across stories**: US2, US3, and US4 all touch `pipeline/run.py` and/or `cli.py`, so they are **not** safe to parallelize with each other despite being logically independent — land them in priority order.

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests first (parallel), confirm failing:
Task: "Unit test composition order + unconditional scoring in tests/unit/test_pipeline_run.py"   # T005
Task: "Unit test argument/flag pass-through in tests/unit/test_pipeline_run.py"                   # T006
Task: "Integration test the end-to-end run in tests/integration/test_run_end_to_end.py"          # T007

# Then implement the seam and wire the command:
Task: "Implement run_pipeline in src/jobhunter/pipeline/run.py"        # T008
Task: "Implement the combined-summary rendering helper"                # T009
Task: "Wire the run command in src/jobhunter/cli.py"                   # T010
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & validate** `jobhunter run` against fake sources + a fixture store (network/LLM mocked; optionally one real run with sources/Ollama available) → demo. This alone turns the two-command discover-then-score workflow into one dependable pipeline command.

### Incremental Delivery

Setup + Foundational → US1 (compose + `run` command, MVP) → US2 (failure-isolation hardening) → US3 (combined summary + observability) → US4 (dry-run rehearsal) — each independently testable and demoable, no regressions between them.

---

## Notes

- `[P]` = different files, no incomplete-task dependency.
- Every implementation task has a preceding failing test (Constitution VII); the composition is tested via stubbed stage runners + fake sources — no live JSearch/Adzuna/Ollama/Claude call is a pass condition.
- **No new runtime dependency and no schema change** this milestone — it composes the existing M2/M3 stages over the existing `jobs.db` (schema stays v2).
- Inherited-by-design (verified, not rebuilt): the single run id (`cli.main()` + `obs`), per-call tracing (each source + the re-rank call), per-source isolation (`run_discovery`), and whole-run-failure ntfy (`cli.main()`).
- Commit after each task or logical group.
- Total: 23 tasks — Setup 2, Foundational 2, US1 6, US2 3, US3 4, US4 3, Polish 3.
