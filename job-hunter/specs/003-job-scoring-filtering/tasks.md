---
description: "Task list for Job Scoring, Filtering & Alerting (M3)"
---

# Tasks: Job Scoring, Filtering & Alerting

**Input**: Design documents from `/specs/003-job-scoring-filtering/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Test-First Development is NON-NEGOTIABLE (Constitution VII). Every task implementing new behavior is preceded by a test written first and observed to fail. The local-embeddings call and the optional LLM re-rank are tested via **mocked HTTP/provider responses** — never a live Ollama or Claude call, and never exact wording as a pass condition.

**Organization**: Grouped by user story so each story is independently implementable and testable. Builds on the M1/M2 package (`src/jobhunter/`) and writes into the existing SQLite store (`jobs.db`, schema bumped to v2 here).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 / US4 (maps to spec.md user stories)
- Paths are relative to repository root; single Python project per [plan.md](./plan.md).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies and package scaffolding for the scoring stage.

- [x] T001 Add `numpy` to the runtime dependencies in `pyproject.toml` (constitution stack — cosine similarity for the `scope` score component) and confirm it installs in the project venv.
- [x] T002 [P] Create the new package skeletons: `src/jobhunter/scoring/__init__.py` and `src/jobhunter/embeddings/__init__.py`.
- [x] T003 [P] Add scoring fixtures under `tests/fixtures/`: a small profile/prefs pair and a representative set of job rows covering every hard-filter dimension (some passing, some failing each) for unit/integration tests to reuse.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The schema shape and the local-embeddings seam every scoring story writes through, established once upfront — matching M1's own precedent of shaping the `jobs` schema ahead of the milestone that populates it.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T004 [P] Unit test the schema migration in `tests/unit/test_store_alerted_at.py`: `init_db` on a fresh store creates `alerted_at` directly; `init_db` on an existing v1 store (no `alerted_at` column) adds it via `ALTER TABLE` without disturbing existing rows; `PRAGMA user_version` reads `2` afterward (write first, confirm failing).
- [x] T005 Implement the `alerted_at` column migration in `src/jobhunter/store/db.py`: check `PRAGMA table_info(jobs)`, `ALTER TABLE jobs ADD COLUMN alerted_at TEXT` only if absent, bump `SCHEMA_VERSION` to `2` — satisfies T004 ([data-model.md](./data-model.md)).
- [x] T006 [P] Unit test the local Ollama embeddings client in `tests/unit/test_embeddings_ollama.py`: a mocked successful HTTP response returns a vector; a connection error/timeout returns `None` (never raises), so callers have a clean fallback signal (write first, confirm failing).
- [x] T007 Implement `embed(text) -> list[float] | None` in `src/jobhunter/embeddings/ollama.py`: POST to the local Ollama `/api/embeddings` endpoint (`mxbai-embed-large`) via `httpx`, bounded timeout, returns `None` on any failure rather than raising — satisfies T006 ([research.md](./research.md) §2).

**Checkpoint**: Schema ready for alerting; local embeddings client ready (with a safe fallback signal) for scoring. User stories can now begin.

---

## Phase 3: User Story 1 — Filter and score newly discovered jobs (Priority: P1) 🎯 MVP

**Goal**: Every `state='new'` job is gated by cheap hard filters from `prefs.yaml`; survivors get a composite score against `prefs.yaml` soft weights and `profile.json`, with the full breakdown and matched skills persisted alongside the score.

**Independent Test**: Seed the store with jobs that fail at least one hard filter and jobs that pass all of them; run `jobhunter score`; verify filtered-out jobs are excluded and marked `state=filtered_out` with a reason, every survivor has `state=scored` with a persisted `score`+`breakdown`+`matched_skills`, and the run reports `filtered_out`/`scored` counts.

### Tests for User Story 1 (write first, confirm failing) ⚠️

- [x] T008 [P] [US1] Unit test hard filters in `tests/unit/test_filters.py`: each dimension (`locations`, `work_modes`, `company_types_allow`/`deny`, `comp_floor_lpa`, `seniority_floor`) passes/fails correctly per [contracts/scoring_algorithm.md](./contracts/scoring_algorithm.md); missing data for a dimension is pass-through, not a failure (FR-003); `failed_filters` lists every violated dimension, not just the first.
- [x] T009 [P] [US1] Unit test the composite scorer's deterministic components in `tests/unit/test_scorer.py`: `comp`/`stability`/`work_life_balance` math (ratio/lookup-table based, neutral `0.5` on missing data); the weighted sum uses `prefs.yaml` weights exactly as configured (no renormalization); `ScoreBreakdown`/`ComponentScore` shape matches data-model.md; `inferred` is `true` only for `stability`/`work_life_balance`. Mocks `embeddings.ollama.embed` for the `scope` component — no live Ollama call.
- [x] T010 [P] [US1] Unit test `matched_skills` selection in `tests/unit/test_matched_skills.py`: profile skills scoring above the similarity threshold against job text are included, ordered by similarity descending; an empty list (not null) when none clear the threshold; falls back to keyword-overlap when `embed` returns `None`.
- [x] T011 [P] [US1] Integration test the scoring run in `tests/integration/test_score_run.py` using fixture jobs/profile/prefs (embeddings mocked, no live call): filtered-out jobs get `state=filtered_out`+`reason` and no score; passing jobs get `state=scored` with `score`+`breakdown`+`matched_skills`; the run reports `filtered_out`/`scored` counts.

### Implementation for User Story 1

- [x] T012 [P] [US1] Implement the hard-filter gate in `src/jobhunter/scoring/filters.py`: produce a `FilterResult` per job per [contracts/scoring_algorithm.md](./contracts/scoring_algorithm.md) — satisfies T008.
- [x] T013 [US1] Implement the composite scorer in `src/jobhunter/scoring/scorer.py`: `comp`/`stability`/`work_life_balance` deterministic components + `scope` via `embeddings.ollama.embed` (keyword-overlap fallback when it returns `None`) + `matched_skills` selection + `ScoreBreakdown` assembly — depends on T007; satisfies T009, T010.
- [x] T014 [US1] Implement the scoring orchestrator in `src/jobhunter/scoring/run.py`: for each `state='new'` job, run filters → on fail: `state=filtered_out`+`reason`; on pass: `score`+`breakdown`+`matched_skills`+`state=scored`; persist via the store; build a `ScoreRunSummary(filtered_out, scored)`; honor `--dry-run` (no writes) — depends on T005, T012, T013; satisfies T011.
- [x] T015 [US1] Wire the `score` command (`--dry-run`) in `src/jobhunter/cli.py` to `scoring.run`; print the run summary to stdout per [contracts/cli.md](./contracts/cli.md).
- [x] T016 [US1] Add observability to the scoring flow (Constitution VIII): wrap the embeddings call (and its fallback path) in `obs.trace("embeddings.embed", ...)` (metadata only) in `scorer.py`; log the per-run summary line; confirm `cli.main()` routes a whole-run failure to `obs.notify_error`.

**Checkpoint**: `jobhunter score` filters and scores independently (MVP).

---

## Phase 4: User Story 2 — Explainable score breakdown (Priority: P2)

**Goal**: Every scored job's persisted breakdown is complete (one score per soft-weight component) and honestly labeled — proxy/inferred signals never presented as directly measured.

**Independent Test**: Score a job against a known profile/prefs fixture; verify the breakdown shows all four components with their contribution, `matched_skills` is retrievable without recomputation, and `stability`/`work_life_balance` are marked `inferred: true` while `scope`/`comp` are not.

### Tests for User Story 2 (write first, confirm failing) ⚠️

- [x] T017 [P] [US2] Unit test breakdown completeness and honesty in `tests/unit/test_score_breakdown.py`: every scored job's breakdown contains all four `SoftWeights` components with `value`/`weight`/`inferred`; two fixture jobs with the same `overall` score show differing component contributions (proving the breakdown, not just the total, is meaningful).
- [x] T018 [P] [US2] Integration test in `tests/integration/test_score_explainability.py`: after a run, every `state=scored` row's `breakdown` JSON round-trips and is queryable directly from the store without recomputation; no row has a non-null `score` with a null `breakdown` (the data-model atomicity rule).

### Implementation for User Story 2

- [x] T019 [US2] Harden `src/jobhunter/scoring/scorer.py` so `score` and `breakdown` are always written together in the same call — never one without the other — depends on T013; satisfies T017, T018.
- [x] T020 [US2] Add a breakdown-rendering helper (e.g. `format_breakdown`) surfaced through the `score` CLI summary so the top contributing factor is legible without a separate query (SC-004) — `src/jobhunter/scoring/scorer.py` and `src/jobhunter/cli.py`.

**Checkpoint**: Explainability is enforced and tested. US1 + US2 work together.

---

## Phase 5: User Story 3 — Alert only on genuinely new, high-scoring jobs (Priority: P3)

**Goal**: A job that is both newly scored and at/above the alert threshold triggers exactly one ntfy notification, ever — never repeated on a later run regardless of rescoring.

**Independent Test**: Run scoring twice over the same above-threshold job; verify exactly one notification fires total across both runs, and a below-threshold job never alerts no matter how many times it's processed.

### Tests for User Story 3 (write first, confirm failing) ⚠️

- [ ] T021 [P] [US3] Unit test alert gating and write-once semantics in `tests/unit/test_alert.py`: `score >= threshold` and `alerted_at IS NULL` → notify + `alerted_at` stamped; `score < threshold` → no notify, `alerted_at` stays `NULL`; `alerted_at` already set → no notify regardless of the current score (mocks `obs.notify`).
- [ ] T022 [P] [US3] Integration test the no-double-alert guarantee in `tests/integration/test_score_rerun_no_realert.py`: two scoring runs over the same above-threshold fixture job → exactly one notification total across both runs; `alerted_at` set once and unchanged on the second run.
- [ ] T023 [P] [US3] Unit test the generalized notify path in `tests/unit/test_obs.py` (extend): `obs.notify(message)` posts when a topic is configured, no-ops otherwise, and never raises on a failed post — mirrors the existing `notify_error` tests.

### Implementation for User Story 3

- [ ] T024 [US3] Generalize `obs.notify_error`'s POST helper into `obs.notify(message)` in `src/jobhunter/obs.py`, used by both the existing error path and the new alert path — satisfies T023.
- [ ] T025 [US3] Implement the alert step in `src/jobhunter/scoring/alert.py`: for this run's `state=scored` jobs with `alerted_at IS NULL` and `score >= alerting.score_threshold`, up to `alerting.max_alerts_per_run`, call `obs.notify` and stamp `alerted_at` — depends on T024; satisfies T021.
- [ ] T026 [US3] Add the write-once `alerted_at` update seam to `src/jobhunter/store/db.py` (a narrow `mark_alerted(id)` function analogous to M2's `touch_last_seen`) — depends on T005.
- [ ] T027 [US3] Wire the alert step into the orchestrator in `src/jobhunter/scoring/run.py`: after scoring, run `alert.py` over this run's newly-scored jobs; add `alerted` to `ScoreRunSummary` — depends on T014, T025, T026; satisfies T022.
- [ ] T028 [US3] Extend observability: trace the alert send (metadata only — job id, outcome, never job content) and include `alerted` in the per-run summary log line.

**Checkpoint**: Alerting is idempotent and dependable. US1–US3 all independently functional.

---

## Phase 6: User Story 4 — Optional qualitative re-rank of top survivors (Priority: P4)

**Goal**: An opt-in `--rerank` pass sends the top ~25 scored survivors through one bounded LLM call for a qualitative fit reason, without being a precondition for filtering, scoring, or alerting.

**Independent Test**: Fixture of 25+ scored survivors with `--rerank` passed; verify only the top ~25 receive an attached reason and exactly one bounded call is made regardless of survivor count; verify omitting `--rerank`, or a provider failure, leaves the rest of the pipeline fully functional.

### Tests for User Story 4 (write first, confirm failing) ⚠️

- [ ] T029 [P] [US4] Unit test the `LLMProvider.rerank` contract in `tests/unit/test_rerank.py`: a mocked provider is called exactly once with at most 25 candidates carrying only title/description/matched-skills + profile skills/roles (never `prefs.yaml` or tracking state); returns a job-id → reason mapping; a provider error/timeout is caught and leaves reasons empty without raising.
- [ ] T030 [P] [US4] Unit test `ClaudeCLIProvider.rerank` in `tests/unit/test_claude_cli.py` (extend): builds the bounded prompt from candidates + profile, parses the response into a job-id → reason mapping, raises `LLMProviderError` on malformed output (mocked `claude -p` call — no live call).
- [ ] T031 [P] [US4] Integration test in `tests/integration/test_score_rerank_optional.py`: a fixture of 25+ scored survivors with `--rerank` → exactly one bounded call, only the top ~25 get `reason` set; running without `--rerank` behaves identically to US1–US3 with `reranked: 0`.

### Implementation for User Story 4

- [ ] T032 [US4] Add the abstract `rerank(candidates, profile) -> dict[str, str]` method to `LLMProvider` in `src/jobhunter/llm/provider.py` (extends the M1 seam) — satisfies T029's contract.
- [ ] T033 [US4] Implement `ClaudeCLIProvider.rerank` in `src/jobhunter/llm/claude_cli.py`: single `claude -p` call, bounded prompt, JSON-parsed response, `LLMProviderError` on malformed output — depends on T032; satisfies T030.
- [ ] T034 [US4] Implement the bounded re-rank orchestration in `src/jobhunter/scoring/rerank.py`: slice this run's `scored` jobs to the top ~25 by `score`, call `provider.rerank` once, write each returned reason into that job's `reason` — depends on T033; satisfies T031.
- [ ] T035 [US4] Wire `--rerank` into the `score` CLI command in `src/jobhunter/cli.py` and the orchestrator in `src/jobhunter/scoring/run.py`: invoke `rerank.py` only when the flag is passed; add `reranked` to `ScoreRunSummary`; a rerank failure logs and continues without affecting persisted scores/alerts — depends on T014, T027, T034.
- [ ] T036 [US4] Add observability: trace the re-rank call (`obs.trace("scoring.rerank", ...)`, metadata only — candidate count/duration/outcome, never job/profile content) and include `reranked` in the per-run summary log line.

**Checkpoint**: All four user stories independently functional; `--rerank` is a strict opt-in addition.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validation and finishing touches spanning stories.

- [ ] T037 [P] Update `README.md`: the `jobhunter score` command, `--dry-run`/`--rerank` flags, the schema v2 note (`alerted_at`), and the local-Ollama prerequisite for the `scope` component (with its keyword-overlap fallback noted).
- [ ] T038 [P] Add CLI error/exit-code tests for `score` in `tests/unit/test_cli_score.py`: missing profile/prefs errors; zero `state=new` jobs is a clean exit-0 no-op; whole-run failure exits non-zero (per [contracts/cli.md](./contracts/cli.md)).
- [ ] T039 Run the [quickstart.md](./quickstart.md) validation end-to-end (fixture jobs; Ollama and `--rerank` both optional) and confirm SC-001…SC-005 are met; fix any gaps.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup — **blocks all user stories** (schema shape + local-embeddings seam).
- **User Stories (Phase 3–6)**: each depends on Foundational. US1 is the MVP; US2 hardens/tests the same `scorer.py` US1 built; US3 and US4 both extend the same `run.py`/`cli.py` US1 built with their own new modules (`alert.py`, `rerank.py`), so within one developer they proceed in priority order P1 → P2 → P3 → P4.
- **Polish (Phase 7)**: depends on the user stories being delivered.

### User Story Dependencies

- **US1 (P1)**: after Phase 2. The foundational MVP slice (filter + score + persist).
- **US2 (P2)**: after US1 — hardens and tests the same `scorer.py`; not safe to parallelize with US1 (shared file).
- **US3 (P3)**: after US1 — adds the alert step on top of US1's `state=scored`/`score` output via new files (`alert.py`, a `mark_alerted` store seam) but also extends the shared `run.py`/`cli.py`.
- **US4 (P4)**: after US1 (and, in practice, after US3 since both extend `run.py`/`cli.py`) — adds the optional re-rank step via new files (`rerank.py`, `llm/provider.py`+`llm/claude_cli.py` extensions).

### Within Each User Story

- Tests written and observed to FAIL before implementation (Constitution VII).
- Filters/scorer/embeddings before the orchestrator; orchestrator before CLI wiring; CLI wiring before observability polish.

### Parallel Opportunities

- Setup: T002, T003 in parallel.
- Foundational: T004 and T006 (different test files) in parallel; their implementations T005/T007 follow respectively.
- US1: all test tasks T008–T011 in parallel (different files); T012 (filters) is independent of T013 (scorer) — both depend only on Foundational, not on each other, so they can proceed in parallel before T014 (orchestrator) ties them together.
- US3: test tasks T021–T023 in parallel.
- US4: test tasks T029–T031 in parallel.
- Across stories: US2, US3, and US4 all touch `scoring/run.py` and/or `cli.py`, so they are **not** safe to parallelize with each other despite being logically independent — land them in priority order.

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests first (parallel), confirm failing:
Task: "Unit test hard filters in tests/unit/test_filters.py"                          # T008
Task: "Unit test composite scorer deterministic components in tests/unit/test_scorer.py"  # T009
Task: "Unit test matched_skills selection in tests/unit/test_matched_skills.py"        # T010
Task: "Integration test the scoring run in tests/integration/test_score_run.py"        # T011

# Then the parallel-safe filter gate alongside the scorer:
Task: "Implement the hard-filter gate in src/jobhunter/scoring/filters.py"   # T012
Task: "Implement the composite scorer in src/jobhunter/scoring/scorer.py"   # T013
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & validate** `jobhunter score` against fixture jobs (embeddings mocked, and, with Ollama running, one real bounded run) → demo. This alone turns the M2 raw inventory into a filtered, explainably-scored shortlist.

### Incremental Delivery

Setup + Foundational → US1 (filter + score, MVP) → US2 (explainability hardening) → US3 (threshold alerting) → US4 (optional re-rank) — each independently testable and demoable, no regressions between them.

---

## Notes

- `[P]` = different files, no incomplete-task dependency.
- Every implementation task has a preceding failing test (Constitution VII); the embeddings call and the LLM re-rank are tested via mocks/fixtures only — no live Ollama or Claude call is a pass condition.
- `numpy` is the one new runtime dependency this milestone adds (cosine similarity); no new HTTP client — the local Ollama call reuses `httpx`.
- Commit after each task or logical group.
- Total: 39 tasks — Setup 3, Foundational 4, US1 9, US2 4, US3 8, US4 8, Polish 3.
