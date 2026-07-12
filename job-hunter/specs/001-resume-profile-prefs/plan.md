# Implementation Plan: Resume Profile & Preferences Foundation

**Branch**: `001-resume-profile-prefs` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-resume-profile-prefs/spec.md`

## Summary

M1 establishes the copilot's foundational state: turn a resume PDF into a persisted structured `Profile` (once), let the user own a hand-editable `prefs.yaml` (hard filters + soft weights, seeded by a one-time guided interview), and stand up the durable SQLite `jobs` store that later milestones (discovery, scoring, triage) will populate. No job discovery or scoring happens here — this milestone delivers the profile, the preferences contract, and an empty-but-shaped store, each independently testable.

Technical approach: a deterministic Python 3.11 package exposing three CLI commands (`profile`, `prefs init`, `db init`). Resume text is extracted with `pypdf`, then structured by an LLM behind a swappable `LLMProvider` interface whose MVP implementation shells out to the Claude Code CLI (`claude -p`, JSON output, Pro-subscription auth — no API key). Preferences are a validated YAML file. The store is SQLite with a versioned schema. Everything is local; the only third-party egress is resume text sent to Claude for structuring.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `pypdf` (PDF text extraction), `PyYAML` (prefs read/write), `pydantic` v2 (schema validation for Profile + Preferences), standard-library `sqlite3` (store), standard-library `subprocess` (Claude Code CLI invocation). No web framework in this milestone (FastAPI arrives in M5).

**Storage**: SQLite database file (`jobs.db`) for the job store; `profile.json` for the persisted structured profile; `prefs.yaml` for user preferences. All under a local app data directory.

**Testing**: `pytest`. TDD is mandatory (Constitution VII): deterministic logic (prefs validation, schema, store CRUD, state-field defaults) tested directly; LLM-touching code (resume parser) tested against fixtures/mocks of provider output — never asserting exact wording, never requiring a live model call.

**Target Platform**: Local macOS (single-user), CLI-invoked.

**Project Type**: Single Python project (CLI + library), no frontend in this milestone.

**Performance Goals**: Not latency-sensitive. Resume parsing is one-time and may take several seconds (bounded by the Claude CLI call). Guided interview completes in under 5 minutes of user time (SC-003). Store operations are trivial at this scale (hundreds–low thousands of rows).

**Constraints**: Offline-capable except for the one resume-structuring call. Resume, profile, and prefs never leave the machine except resume text sent to Claude for structuring (Constitution I, FR-014). Zero incremental spend — reuse the Pro subscription via `claude -p` (Constitution II).

**Scale/Scope**: Single user, single profile, single prefs file, one SQLite store. Job-record volume is out of scope for this milestone (store is created empty).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|---|---|---|
| I. Explicit LLM Provider Boundaries | Resume structuring is the only LLM touchpoint here and sits behind an `LLMProvider` interface; MVP impl = `claude -p` (no API key). Only resume text is sent; prefs/profile/store stay local. No embeddings needed in this milestone. | PASS |
| II. Bounded Usage, Zero Incremental Cost | LLM runs once per resume (not per-run, not per-job). No metered billing. | PASS |
| III. Ethical Boundaries | No auto-apply, no scraping, no external job sources touched in M1. | PASS (N/A) |
| IV. Monitor, Not Search (Idempotent State) | Store schema includes stable `id`, `first_seen`/`last_seen`, and per-job `state` so later milestones can be idempotent. Schema defined here to honor this. | PASS |
| V. Explainable Ranking | Store schema reserves `score`, `breakdown`, `matched_skills`, `reason` fields so ranking is explainable when M3 populates them. | PASS |
| VI. Deterministic Simplicity (YAGNI) | Plain Python, no agent framework. Only the resume parser touches an LLM. CLI + stdlib SQLite. | PASS |
| VII. Test-First Development | Plan mandates tests-first for all deterministic logic; parser tested via fixtures. Enforced in tasks. | PASS |

**Technology & Operational Constraints**: Stack matches the constitution (Python 3.11+, SQLite, pypdf, Claude Code CLI). SQLite is the single source of truth. Filter-before-score, resilience, and scheduling constraints are not exercised in M1 (no discovery yet) but the store schema is laid so they hold later.

**Result**: PASS — no violations. Complexity Tracking not required.

**Post-design re-check (after Phase 1)**: The data model, contracts, and quickstart introduced no new LLM touchpoints, no agent framework, and no external network egress beyond the single resume-structuring call already accounted for. Store schema carries the idempotency (IV) and explainability (V) fields. Still PASS.

## Project Structure

### Documentation (this feature)

```text
specs/001-resume-profile-prefs/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (CLI + schema contracts)
│   ├── cli.md
│   ├── profile.schema.json
│   └── prefs.schema.md
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

```text
src/
└── jobhunter/
    ├── __init__.py
    ├── cli.py                 # CLI entrypoint: `profile`, `prefs init`, `db init`
    ├── config.py              # App data dir resolution, file paths
    ├── models/
    │   ├── __init__.py
    │   ├── profile.py         # Profile pydantic model + persistence (profile.json)
    │   └── preferences.py     # Preferences pydantic model + YAML load/validate
    ├── resume/
    │   ├── __init__.py
    │   ├── extract.py         # pypdf text extraction
    │   └── parser.py          # resume text -> Profile via LLMProvider
    ├── llm/
    │   ├── __init__.py
    │   ├── provider.py        # LLMProvider interface (swappable)
    │   └── claude_cli.py      # MVP impl: `claude -p` JSON via subprocess
    ├── prefs/
    │   ├── __init__.py
    │   └── interview.py       # one-time guided interview -> prefs.yaml
    └── store/
        ├── __init__.py
        └── db.py              # SQLite schema init + job-record CRUD

tests/
├── unit/
│   ├── test_preferences_validation.py
│   ├── test_profile_model.py
│   ├── test_store_schema.py
│   └── test_resume_extract.py
├── integration/
│   ├── test_resume_parser.py      # uses fixture/mock LLMProvider
│   ├── test_prefs_interview.py
│   └── test_db_roundtrip.py
└── fixtures/
    ├── sample_resume.pdf
    └── claude_profile_response.json
```

**Structure Decision**: Single Python package `src/jobhunter/` with a thin `cli.py`, organized by concern (models, resume, llm, prefs, store). This matches Constitution VI (deterministic, no framework) and gives later milestones clear seams: `llm/provider.py` is the swap point for Ollama, `store/db.py` is the single source of truth, and new discovery sources will land under a future `sources/` package implementing a `JobSource` interface.

## Complexity Tracking

> No Constitution Check violations. Section intentionally empty.
