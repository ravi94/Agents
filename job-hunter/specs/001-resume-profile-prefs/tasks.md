---
description: "Task list for Resume Profile & Preferences Foundation (M1)"
---

# Tasks: Resume Profile & Preferences Foundation

**Input**: Design documents from `/specs/001-resume-profile-prefs/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Test-First Development is NON-NEGOTIABLE (Constitution VII). Every task implementing new behavior is preceded by a test that is written first and observed to fail. LLM-touching work (resume parser) is tested via mocked/fixture provider responses — never asserting exact wording, never requiring a live `claude` call.

**Organization**: Grouped by user story so each story is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 (maps to spec.md user stories)
- Paths are relative to repository root; single Python project per [plan.md](./plan.md).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project scaffolding and tooling.

- [X] T001 Create the package structure per plan.md: `src/jobhunter/` with `models/`, `resume/`, `llm/`, `prefs/`, `store/` subpackages (each with `__init__.py`), plus `tests/unit/`, `tests/integration/`, `tests/fixtures/`.
- [X] T002 Create `pyproject.toml` at repo root declaring Python 3.11+, dependencies (`pypdf`, `PyYAML`, `pydantic>=2`), dev dependency `pytest`, and a `jobhunter` console-script entry point pointing at `src/jobhunter/cli.py`.
- [X] T003 [P] Configure linting/formatting (ruff config in `pyproject.toml`) and add `pytest` config (test paths, `-q`) to `pyproject.toml`.
- [X] T004 [P] Add test fixtures: a small text-extractable `tests/fixtures/sample_resume.pdf`, an image-only `tests/fixtures/scanned_image.pdf`, and `tests/fixtures/claude_profile_response.json` (a representative `claude -p` JSON structuring response).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared infrastructure every user story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 Implement app data directory + path resolution in `src/jobhunter/config.py`: resolve `JOBHUNTER_HOME` env var (default `~/.job-hunter/`), expose paths for `profile.json`, `prefs.yaml`, `jobs.db`, and ensure the directory exists.
- [X] T006 [P] Create the CLI skeleton in `src/jobhunter/cli.py`: argument parser with `profile`, `prefs` (subcommands `init`, `validate`), and `db init` commands wired to placeholder handlers; errors to stderr, summaries to stdout; non-zero exit on failure.
- [X] T007 [P] Write the unit test for `config.py` path resolution in `tests/unit/test_config.py` (default vs `JOBHUNTER_HOME` override) — confirm failing, then covered by T005.

**Checkpoint**: Package importable, CLI dispatches, paths resolve. User stories can now begin.

---

## Phase 3: User Story 1 — Resume → persisted profile (Priority: P1) 🎯 MVP

**Goal**: A resume PDF becomes a validated, persisted structured `Profile` reused on later runs; failures leave any existing profile intact.

**Independent Test**: Run `jobhunter profile tests/fixtures/sample_resume.pdf`; verify `profile.json` is written with non-empty skills; re-run needs no resubmission; an image-only PDF errors with no write.

### Tests for User Story 1 (write first, confirm failing) ⚠️

- [X] T008 [P] [US1] Unit test for PDF text extraction in `tests/unit/test_resume_extract.py`: extracts text from `sample_resume.pdf`; raises a clear error (no text) for `scanned_image.pdf`.
- [X] T009 [P] [US1] Unit test for the `Profile` pydantic model in `tests/unit/test_profile_model.py`: valid parse from `claude_profile_response.json`; rejects empty `skills`; `seniority`/nullable fields default to null (never fabricated); validates against `contracts/profile.schema.json`.
- [X] T010 [P] [US1] Integration test for the resume parser in `tests/integration/test_resume_parser.py` using a mock/fixture `LLMProvider` (no live `claude`): end-to-end resume → Profile; asserts atomic write leaves a prior `profile.json` intact on provider failure/malformed JSON; asserts only resume text is passed to the provider (FR-014).

### Implementation for User Story 1

- [X] T011 [US1] Implement PDF text extraction in `src/jobhunter/resume/extract.py` (`pypdf`), raising a clear error on empty/near-empty output (image-only) — satisfies T008.
- [X] T012 [US1] Implement the `Profile` model + atomic JSON persistence (load/save to `profile.json`) in `src/jobhunter/models/profile.py` per `contracts/profile.schema.json` — satisfies T009.
- [X] T013 [P] [US1] Define the `LLMProvider` interface (`structure_resume(text) -> Profile`) in `src/jobhunter/llm/provider.py` (the swap seam for Ollama, Constitution I).
- [X] T014 [US1] Implement the Claude Code CLI provider in `src/jobhunter/llm/claude_cli.py`: invoke `claude -p ... --output-format json` via `subprocess`, parse/validate the JSON into a `Profile`, handle timeouts/non-zero exit/malformed output with clear errors (depends on T012, T013).
- [X] T015 [US1] Implement the parser orchestration in `src/jobhunter/resume/parser.py`: extract → provider.structure_resume → validate → atomic write; on any failure, do not write and leave existing profile intact (depends on T011, T012, T013) — satisfies T010.
- [X] T016 [US1] Wire the `profile <resume.pdf>` command in `src/jobhunter/cli.py` to the parser; print skills count / seniority / roles summary and the written path; non-zero exit + actionable error on failure (per `contracts/cli.md`).

**Checkpoint**: User Story 1 fully functional and independently testable (MVP).

---

## Phase 4: User Story 2 — Preferences via guided interview + hand-edit (Priority: P2)

**Goal**: A one-time guided interview seeds `prefs.yaml` (hard filters + soft weights); the file is hand-editable and validated on load, with clear per-field errors and weight-sum warnings; the interview never silently re-runs or overwrites edits.

**Independent Test**: Run `jobhunter prefs init` → `prefs.yaml` created; hand-edit a value → `jobhunter prefs validate` honors it without re-interview; `prefs init` refuses without `--force`; a bad `work_modes` value errors naming the field; a 0.9 weight sum warns but passes.

### Tests for User Story 2 (write first, confirm failing) ⚠️

- [X] T017 [P] [US2] Unit test for `Preferences` validation in `tests/unit/test_preferences_validation.py`: valid file parses; invalid `work_modes`/negative `comp_floor_lpa`/out-of-enum `seniority_floor`/allow∩deny overlap/out-of-range weights & `score_threshold`/negative `max_alerts_per_run` each error naming the field; weight sum ≠ 1.0 warns but preserves values (FR-008); empty `locations` errors.
- [X] T018 [P] [US2] Integration test for the interview + reload in `tests/integration/test_prefs_interview.py` (mock stdin): interview writes a schema-valid `prefs.yaml`; `init` refuses when the file exists (no `--force`); an interrupted/aborted interview writes nothing; a hand-edited value is honored on reload without re-running the interview.

### Implementation for User Story 2

- [X] T019 [P] [US2] Implement the `Preferences` pydantic model + YAML load/validate in `src/jobhunter/models/preferences.py` per `contracts/prefs.schema.md` (errors name the field; weight-sum drift is a warning, not an error) — satisfies T017.
- [X] T020 [US2] Implement the guided interview in `src/jobhunter/prefs/interview.py`: fixed question set → build & write `prefs.yaml`; write nothing on abort; refuse to overwrite an existing file unless forced (depends on T019) — satisfies T018.
- [X] T021 [US2] Wire `prefs init [--force]` and `prefs validate` commands in `src/jobhunter/cli.py` (validate prints warnings but exits 0 when valid; exits non-zero naming the offending field when invalid) per `contracts/cli.md`.

**Checkpoint**: User Stories 1 and 2 both work independently.

---

## Phase 5: User Story 3 — Durable job store (Priority: P3)

**Goal**: `jobs.db` is created with the full `jobs` schema (idempotency + explainability fields) and `PRAGMA user_version`; init is idempotent; a written record round-trips unchanged with `state` defaulting to `new`.

**Independent Test**: Run `jobhunter db init` twice → store created then reused (not wiped); write a job record and read it back with all fields unchanged, `state='new'`, timestamps populated.

### Tests for User Story 3 (write first, confirm failing) ⚠️

- [X] T022 [P] [US3] Unit test for schema creation in `tests/unit/test_store_schema.py`: `db init` creates the `jobs` table with every column from data-model.md, sets `PRAGMA user_version`, and is idempotent (second init preserves existing rows — not wiped).
- [X] T023 [P] [US3] Integration test for record round-trip in `tests/integration/test_db_roundtrip.py`: insert a job record, read it back with all fields unchanged; `state` defaults to `new`; `first_seen`/`last_seen`/`updated_at` populated; store persists across separate connections/runs.

### Implementation for User Story 3

- [X] T024 [US3] Implement the store in `src/jobhunter/store/db.py`: `init_db()` (`CREATE TABLE IF NOT EXISTS jobs(...)` per data-model.md + set `user_version`, idempotent) and minimal `upsert_job`/`get_job` CRUD with parameterized queries and `state` default `new` — satisfies T022, T023.
- [X] T025 [US3] Wire the `db init` command in `src/jobhunter/cli.py` to `init_db()`; print the `jobs.db` path and schema version per `contracts/cli.md`.

**Checkpoint**: All three user stories independently functional.

---

## Phase 5b: Observability (Constitution Principle VIII — cross-cutting)

**Purpose**: Every feature ships observable — a run correlation id threaded
through structured logs, tracing (metadata only) of LLM/external calls, a
rotating log file, and an ntfy error signal on failure. Foundational infra is
shared; each story wires its own calls/run signals.

- [X] T029 [Obs] Foundational observability module in `src/jobhunter/obs.py` (run-id logging filter, `RotatingFileHandler` under `logs/`, `trace()` context manager, `notify_error()` ntfy hook) + `config.log_path()`/`logs_dir()` — tests in `tests/unit/test_obs.py` (write first, confirm failing).
- [X] T030 [US1] Wire tracing into the profile flow: trace `resume.extract` and `llm.structure_resume` in `resume/parser.py`; configure run logging + run start/end + ntfy-on-error in `cli.py` `main()`.
- [X] T031 [US2] Wire observability into `prefs init`/`validate`: trace the interview + validation, log per-run outcome, ntfy on failure (lands with T019–T021).
- [X] T032 [US3] Wire observability into `db init`: trace schema creation, log the outcome/version, ntfy on failure (lands with T024–T025).

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validation and finishing touches spanning stories.

- [ ] T026 [P] Add a `README.md` (or `docs/`) section covering install (`pip install -e .`), Claude CLI login prerequisite, and the three commands.
- [ ] T027 [P] Add unit tests for CLI error/exit-code behavior across all three commands in `tests/unit/test_cli_errors.py` (stderr messages, non-zero exits).
- [ ] T028 Run the full [quickstart.md](./quickstart.md) validation end-to-end and confirm SC-001…SC-006 are met; fix any gaps.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup — **blocks all user stories**.
- **User Stories (Phase 3–5)**: each depends only on Foundational; independent of one another — can proceed in parallel or in priority order P1 → P2 → P3.
- **Polish (Phase 6)**: depends on the user stories being delivered.

### User Story Dependencies

- **US1 (P1)**: after Phase 2. No dependency on US2/US3.
- **US2 (P2)**: after Phase 2. Independent of US1/US3.
- **US3 (P3)**: after Phase 2. Independent of US1/US2.

### Within Each User Story

- Tests written and observed to FAIL before implementation (Constitution VII).
- Models before services/orchestration; orchestration before CLI wiring.

### Parallel Opportunities

- Setup: T003, T004 in parallel.
- Foundational: T006, T007 in parallel (after T005).
- Once Phase 2 is done, US1 / US2 / US3 can be built by different developers in parallel.
- Within each story, all `[P]` test tasks run in parallel; independent models (e.g., T013) parallel with model work in other files.

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests first (parallel), confirm failing:
Task: "Unit test PDF extraction in tests/unit/test_resume_extract.py"        # T008
Task: "Unit test Profile model in tests/unit/test_profile_model.py"          # T009
Task: "Integration test resume parser in tests/integration/test_resume_parser.py"  # T010

# Then parallel-safe implementation pieces:
Task: "Define LLMProvider interface in src/jobhunter/llm/provider.py"         # T013
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & validate** `jobhunter profile` end-to-end → demo. This alone delivers the profile every later milestone depends on.

### Incremental Delivery

Setup + Foundational → US1 (MVP) → US2 (preferences) → US3 (store) — each independently testable and demoable, no regressions between them.

---

## Notes

- `[P]` = different files, no incomplete-task dependency.
- Every implementation task has a preceding failing test (Constitution VII); LLM tests use fixtures/mocks only (no live `claude` call as a pass condition).
- Commit after each task or logical group.
- Total: 28 tasks — Setup 4, Foundational 3, US1 9, US2 5, US3 4, Polish 3.
