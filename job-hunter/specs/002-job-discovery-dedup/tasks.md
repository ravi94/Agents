---
description: "Task list for Job Discovery, Normalization & Dedup (M2)"
---

# Tasks: Job Discovery, Normalization & Dedup

**Input**: Design documents from `/specs/002-job-discovery-dedup/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Test-First Development is NON-NEGOTIABLE (Constitution VII). Every task implementing new behavior is preceded by a test written first and observed to fail. Source-touching work (JSearch/Adzuna adapters, the run) is tested via **fixture payloads and a fixture `JobSource`** — never a live API call, never a credential requirement as a pass condition.

**Organization**: Grouped by user story so each story is independently implementable and testable. Builds on the M1 package (`src/jobhunter/`) and writes into the existing M1 SQLite store.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 (maps to spec.md user stories)
- Paths are relative to repository root; single Python project per [plan.md](./plan.md).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies and package scaffolding for the discovery stage.

- [ ] T001 Add `httpx` to the runtime dependencies in `pyproject.toml` (constitution stack) and confirm it installs in the project venv.
- [ ] T002 [P] Create the new package skeletons: `src/jobhunter/sources/__init__.py` and `src/jobhunter/discovery/__init__.py`.
- [ ] T003 [P] Add source fixtures under `tests/fixtures/`: `jsearch_response.json`, `adzuna_response.json` (representative captured payloads per `contracts/source_mapping.md`), and `source_dupe_pair.json` (the same role from both sources, for cross-source dedup).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared fetch infrastructure every source and the run depend on: the pluggable interface, the rate-limit-safe HTTP wrapper, and the response cache.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T004 Define the `JobSource` interface and the `SearchQuery`, `RawPosting`, and `SourceError` types in `src/jobhunter/sources/base.py` per [contracts/job_source.md](./contracts/job_source.md) (the swap seam for the future ATS source, Constitution VI/FR-002).
- [ ] T005 [P] Unit test the HTTP wrapper in `tests/unit/test_http_backoff.py`: bounded retry count on HTTP 429, exponential backoff, and `Retry-After` honored; gives up after the cap (write first, confirm failing).
- [ ] T006 Implement the httpx wrapper in `src/jobhunter/http.py` (bounded retries, exponential backoff, `Retry-After`, timeouts) — satisfies T005; the single HTTP path all sources route through (FR-006).
- [ ] T007 [P] Unit test the response cache in `tests/unit/test_cache.py`: a hit within the TTL is served without a call; a miss/expiry re-fetches; keys are stable per (source, endpoint, params) (write first, confirm failing).
- [ ] T008 Implement `config.cache_dir()` in `src/jobhunter/config.py` and the file-based response cache in `src/jobhunter/sources/cache.py` (hashed key, stored timestamp, bounded TTL) — satisfies T007 (FR-005, free-tier protection).

**Checkpoint**: Interface, rate-limit-safe HTTP, and caching ready. User stories can now begin.

---

## Phase 3: User Story 1 — Discover and persist genuinely new jobs (Priority: P1) 🎯 MVP

**Goal**: A `jobhunter discover` run queries one source, normalizes each posting into a canonical `Job`, dedups within the run, and persists never-before-seen jobs into the M1 store with `state=new` and `first_seen` set — no scoring, no alerting.

**Independent Test**: Run `jobhunter discover` against a fixture `JobSource`; verify each posting becomes a canonical row with required identity + a `work_mode` value, new rows carry `state=new` / `first_seen` / `last_seen` and null `score`, and the run prints a `fetched/new/skipped` summary. `--dry-run` writes nothing.

### Tests for User Story 1 (write first, confirm failing) ⚠️

- [ ] T009 [P] [US1] Unit test query derivation in `tests/unit/test_query.py`: `profile.roles` × `prefs.locations` builds queries; an optional `prefs.search.keywords` override replaces the profile keywords; empty profile+prefs → zero queries (clean no-op).
- [ ] T010 [P] [US1] Unit test JSearch normalization in `tests/unit/test_normalize.py`: `jsearch_response.json` maps to canonical `Job` fields per `contracts/source_mapping.md`; absent optional fields (salary, etc.) are null — never fabricated (FR-010); a posting missing title+company is skipped and counted (FR-011).
- [ ] T011 [P] [US1] Unit test work-mode classification in `tests/unit/test_work_mode.py`: explicit remote flag → `remote`; text keywords → `hybrid`/`onsite`; no signal → `unknown` (never guessed) (FR-009).
- [ ] T012 [P] [US1] Unit test idempotency key + within-run dedup in `tests/unit/test_dedup.py`: source-id vs normalized `title|company|city` composite; duplicate postings in one batch collapse to one; unusable-id postings are skipped (FR-011, FR-012, FR-013).
- [ ] T013 [P] [US1] Integration test single-source discovery in `tests/integration/test_discover_run.py` using a fixture `JobSource` (no live call): end-to-end fetch→normalize→dedup→persist against a temp `JOBHUNTER_HOME`; asserts new rows with `state=new`/`first_seen`/`last_seen`, null `score`, and a run summary of `fetched`/`new`/`skipped`.

### Implementation for User Story 1

- [ ] T014 [US1] Add the optional `search` block (`SearchPrefs` with `keywords`) to `src/jobhunter/models/preferences.py` — additive, `extra="forbid"` preserved so existing M1 `prefs.yaml` files still validate (data-model.md).
- [ ] T015 [US1] Implement query derivation in `src/jobhunter/discovery/query.py` (profile roles/seniority × prefs locations; `prefs.search` override; empty → no queries) — depends on T014; satisfies T009.
- [ ] T016 [US1] Implement the work-mode classification helper in `src/jobhunter/discovery/normalize.py` (explicit flag → text inference → `unknown`) — satisfies T011.
- [ ] T017 [US1] Implement JSearch payload → canonical `Job` normalization + idempotency-key computation in `src/jobhunter/discovery/normalize.py` (uses the work-mode helper; skips unnormalizable postings) — depends on T016; satisfies T010.
- [ ] T018 [US1] Implement the idempotency key + within-run dedup (new-vs-store lookup, new path) in `src/jobhunter/discovery/dedup.py` — satisfies T012.
- [ ] T019 [P] [US1] Implement the JSearch source adapter in `src/jobhunter/sources/jsearch.py`: build requests from `SearchQuery`, route through `http.py` + cache, respect the per-source query budget, raise `SourceError` on failure, and skip itself when `JSEARCH_API_KEY` is absent (contracts/job_source.md).
- [ ] T020 [US1] Implement the run orchestrator (single-source path) in `src/jobhunter/discovery/run.py`: derive queries → `source.fetch` → normalize → dedup → persist new via `store.upsert_job` → build the `RunSummary`; honor `--dry-run` (no writes) — depends on T015–T019; satisfies T013.
- [ ] T021 [US1] Wire the `discover` command (`--source`, `--dry-run`) in `src/jobhunter/cli.py` to `discovery.run`; print the run summary to stdout; whole-run failure exits non-zero (per [contracts/cli.md](./contracts/cli.md)).
- [ ] T022 [US1] Add observability to the discover flow (Constitution VIII): wrap each source fetch in `obs.trace("source.fetch", source=…)` (metadata only) in `run.py`, log the per-run summary line at run end, and confirm `cli.main()` routes a whole-run failure to `obs.notify_error` (ntfy).

**Checkpoint**: `jobhunter discover` captures new jobs from one source, independently testable (MVP).

---

## Phase 4: User Story 2 — Re-run without duplicates (monitor semantics) (Priority: P2)

**Goal**: Re-running discovery recognizes already-seen postings by their idempotency key, advances only `last_seen`, and never re-adds them or resets their `state` — turning discovery into a monitor.

**Independent Test**: Run discovery twice over the same fixture response; verify no duplicate rows, already-seen rows' `last_seen` advanced while `first_seen`/`state` unchanged (including a row pre-set to `interested`), and the summary distinguishes `new` vs `seen`.

### Tests for User Story 2 (write first, confirm failing) ⚠️

- [ ] T023 [P] [US2] Unit test `touch_last_seen` in `tests/unit/test_store_touch_last_seen.py`: advances `last_seen`; leaves `first_seen`, `state`, `updated_at`, and content columns unchanged; no-op (returns False) when the id is absent (FR-015).
- [ ] T024 [P] [US2] Integration test idempotent re-run in `tests/integration/test_discover_idempotent.py`: a second run over the same fixture adds zero duplicate rows; already-seen rows get `last_seen` advanced with `first_seen`/`state` preserved; a job pre-set to `interested` is not reset to `new`; the summary reports `seen` vs `new` (FR-013–015, SC-002).

### Implementation for User Story 2

- [ ] T025 [US2] Implement `touch_last_seen(id, path=None)` in `src/jobhunter/store/db.py`: advance `last_seen` only, preserving `first_seen`/`state`/`updated_at`; no-op if absent — satisfies T023 (reuses M1 `upsert_job` unchanged for the new path).
- [ ] T026 [US2] Extend dedup/persist across runs in `src/jobhunter/discovery/dedup.py` and `src/jobhunter/discovery/run.py`: existing id → `touch_last_seen` (seen path), new id → `upsert_job`; tally `new` vs `seen` in the `RunSummary` — satisfies T024.
- [ ] T027 [US2] Extend observability: include `seen` vs `new` counts in the per-run summary and trace persist outcomes (metadata only) in `run.py`.

**Checkpoint**: Discovery is idempotent across runs — a monitor, not a repeated search. US1 + US2 both work.

---

## Phase 5: User Story 3 — Resilient multi-source discovery (Priority: P3)

**Goal**: Discovery queries multiple sources through the common interface, dedups a role appearing in more than one source into a single record, and completes the run even when a source errors, times out, or is rate-limited.

**Independent Test**: Run discovery with two fixture sources where one raises `SourceError`; verify the run completes (exit 0), stores the healthy source's new jobs, and lists the failed source in the summary. Feed the same role from both sources and verify it is stored once.

### Tests for User Story 3 (write first, confirm failing) ⚠️

- [ ] T028 [P] [US3] Unit test Adzuna normalization in `tests/unit/test_normalize_adzuna.py`: `adzuna_response.json` maps to canonical `Job`; work mode is text-inferred (no explicit flag); the stable Adzuna id is used while a composite is still recorded for cross-source collapse (contracts/source_mapping.md).
- [ ] T029 [P] [US3] Unit test cross-source dedup in `tests/unit/test_dedup_cross_source.py` using `source_dupe_pair.json`: the same role from both sources collapses to one record, preferring the richer payload deterministically (FR-013, SC-004).
- [ ] T030 [P] [US3] Integration test resilience in `tests/integration/test_discover_resilience.py`: two fixture sources, one raising `SourceError` → run completes exit 0, the healthy source's new jobs are stored, and the failed source is recorded in the summary; partial results are a success (FR-017–018, SC-003).

### Implementation for User Story 3

- [ ] T031 [P] [US3] Implement the Adzuna India source adapter in `src/jobhunter/sources/adzuna.py`: build requests from `SearchQuery`, route through `http.py` + cache, respect the query budget, raise `SourceError` on failure, and skip itself when `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` are absent.
- [ ] T032 [US3] Implement Adzuna payload → canonical `Job` normalization in `src/jobhunter/discovery/normalize.py` (stable source id + recorded composite for cross-source collapse) — satisfies T028.
- [ ] T033 [US3] Extend the orchestrator in `src/jobhunter/discovery/run.py` and cross-source dedup in `src/jobhunter/discovery/dedup.py`: iterate all configured sources with per-source try/except isolation, collapse cross-source duplicates, and record per-source counts/failures in the `RunSummary` — satisfies T029, T030.
- [ ] T034 [US3] Extend observability: record each source's outcome (ok/failed + reason, metadata only) in the summary and traces; ensure a dead source is logged, traced, and skipped — never escalated to a whole-run failure (FR-017/024).

**Checkpoint**: Multi-source discovery is dependable under partial failure. All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validation and finishing touches spanning stories.

- [ ] T035 [P] Update `README.md`: the `jobhunter discover` command, source credential env vars (`JSEARCH_API_KEY`, `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`), and the free-tier/caching note.
- [ ] T036 [P] Add CLI error/exit-code tests for `discover` in `tests/unit/test_cli_discover.py`: missing profile/prefs errors; no-usable-query is a clean exit 0 no-op; whole-run failure exits non-zero (per contracts/cli.md).
- [ ] T037 Run the [quickstart.md](./quickstart.md) validation end-to-end with fixture sources and confirm SC-001…SC-007 are met; fix any gaps.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup — **blocks all user stories** (interface + HTTP + cache).
- **User Stories (Phase 3–5)**: each depends on Foundational. US1 is the MVP; US2 and US3 build on US1's normalization/run seams (they extend the same `run.py`/`dedup.py`/`normalize.py`), so within one developer they proceed in priority order P1 → P2 → P3.
- **Polish (Phase 6)**: depends on the user stories being delivered.

### User Story Dependencies

- **US1 (P1)**: after Phase 2. The foundational MVP slice (single-source discover + persist-new).
- **US2 (P2)**: after US1 — reuses US1's run/dedup and adds the `touch_last_seen` seen-path.
- **US3 (P3)**: after US1 — adds the second source + resilience/cross-source dedup on US1's normalization + orchestration. Independent of US2's idempotency logic but shares files, so land after US2 to avoid churn.

### Within Each User Story

- Tests written and observed to FAIL before implementation (Constitution VII).
- Models/helpers before services; services before the orchestrator; orchestrator before CLI wiring.

### Parallel Opportunities

- Setup: T002, T003 in parallel.
- Foundational: the test tasks T005 and T007 in parallel (different files); their impls T006/T008 follow.
- US1: all test tasks T009–T013 in parallel; the JSearch adapter T019 parallels the normalize/dedup work (different files).
- US3: test tasks T028–T030 in parallel; the Adzuna adapter T031 parallels its normalization/orchestrator wiring.
- Across stories: US2 and US3 touch overlapping files (`run.py`, `dedup.py`, `normalize.py`), so they are NOT safe to parallelize with each other despite being logically independent.

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests first (parallel), confirm failing:
Task: "Unit test query derivation in tests/unit/test_query.py"                 # T009
Task: "Unit test JSearch normalization in tests/unit/test_normalize.py"        # T010
Task: "Unit test work-mode classification in tests/unit/test_work_mode.py"     # T011
Task: "Unit test idempotency key + dedup in tests/unit/test_dedup.py"          # T012
Task: "Integration test single-source discovery in tests/integration/test_discover_run.py"  # T013

# Then the parallel-safe adapter alongside normalize/dedup:
Task: "Implement the JSearch source adapter in src/jobhunter/sources/jsearch.py"  # T019
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & validate** `jobhunter discover` against a fixture source (and, with credentials, one real bounded run) → demo. This alone turns the empty M1 store into a populated, inspectable inventory.

### Incremental Delivery

Setup + Foundational → US1 (single-source discover, MVP) → US2 (idempotent monitor) → US3 (multi-source + resilience) — each independently testable and demoable, no regressions between them.

---

## Notes

- `[P]` = different files, no incomplete-task dependency.
- Every implementation task has a preceding failing test (Constitution VII); source adapters and the run are tested via fixtures/mocks only — no live API call is a pass condition.
- No LLM or embedding work in M2; the only external egress is the job-source APIs (public data + query metadata, FR-021).
- Commit after each task or logical group.
- Total: 37 tasks — Setup 3, Foundational 5, US1 14, US2 5, US3 7, Polish 3.
