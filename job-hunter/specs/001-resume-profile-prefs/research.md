# Phase 0 Research: Resume Profile & Preferences Foundation

The stack is largely fixed by the constitution, so this milestone had few open unknowns. Each below records a decision, its rationale, and rejected alternatives.

## R1. Resume structuring via Claude Code CLI (MVP LLM provider)

- **Decision**: Extract raw text with `pypdf`, then call `claude -p "<prompt>" --output-format json` via `subprocess`, passing resume text plus a JSON-schema instruction, and parse the returned JSON into a `Profile`. The call sits behind an `LLMProvider.structure_resume(text) -> Profile` interface.
- **Rationale**: Constitution I mandates the Claude Code CLI (Pro-subscription auth, no metered API key) as the MVP text-generation provider behind a swappable interface. `claude -p` non-interactive mode is Anthropic's supported path for scripted use under a Pro login. Zero incremental spend (Constitution II).
- **Alternatives considered**:
  - *Anthropic Messages API with an API key* — rejected: no API key is provisioned and the constitution forbids metered billing.
  - *Local Ollama (Qwen2.5) now* — rejected for MVP: it's the committed fast-follow, but the provider interface makes the swap a later, isolated change; doing it now delays the working spine.
  - *Regex/heuristic parsing (no LLM)* — rejected: brittle across resume formats; the LLM produces far higher-quality structure with a bounded one-time cost.

## R2. Handling unstructured / non-extractable resumes

- **Decision**: If `pypdf` yields empty or near-empty text (scanned/image-only PDF), fail fast with a clear, specific error and do not invoke the LLM or write any profile. OCR is explicitly out of scope (spec Assumptions).
- **Rationale**: Satisfies FR-012 (clear error, no corrupted profile) and the edge case for image-only resumes. Avoids spending an LLM call on garbage input.
- **Alternatives considered**: *Bundle an OCR engine* — rejected as scope creep for a single-user local tool with a text PDF assumption.

## R3. Profile persistence format

- **Decision**: Persist the structured profile as `profile.json` (a JSON file), validated on read and write through a `pydantic` model. Writes are atomic (write to temp file, then rename) so a failed parse never corrupts an existing profile.
- **Rationale**: JSON is the natural output of the LLM call, is trivially serializable from pydantic, and keeps the profile human-inspectable and local (FR-003, FR-014). Atomic write satisfies FR-012's "no corrupted profile" requirement. A new resume submission overwrites it (FR-004).
- **Alternatives considered**:
  - *Store the profile as a row in SQLite* — rejected: the profile is a single-object, single-user artifact; a standalone JSON file is simpler to inspect and edit, and keeps the `jobs.db` purely for job records.
  - *YAML for the profile* — rejected: JSON matches the LLM output directly and needs no round-trip translation; YAML is reserved for the hand-edited prefs where human ergonomics matter more.

## R4. Preferences file format and validation

- **Decision**: `prefs.yaml` in the exact shape from the HLD (§6): `hard_filters`, `soft_weights`, `alerting`. Load with `PyYAML`, validate with a `pydantic` model on every read. On invalid edits, raise a clear error naming the offending field (FR-013). Soft weights summing to ~1.0 is a **warning**, not a hard failure (spec Assumptions).
- **Rationale**: YAML is human-friendly for hand-editing (FR-007); pydantic gives per-field validation messages for free. Matching the HLD shape means M3's scorer can consume it unchanged.
- **Alternatives considered**:
  - *TOML/JSON prefs* — rejected: YAML is the format already specified in the HLD and is the most comment- and edit-friendly for the user.
  - *Hard-fail on weight sum ≠ 1.0* — rejected: the HLD calls weights "sum ~1.0" (guidance); the system normalizes/warns rather than blocking the user's intent (FR-008).

## R5. Guided interview mechanics

- **Decision**: A one-time terminal Q&A (`prefs init`) that asks a short, fixed set of questions (locations, work modes, allowed/denied company types, comp floor, seniority floor, and relative importance of the four soft factors), then writes `prefs.yaml`. If `prefs.yaml` already exists, the command refuses to overwrite unless the user passes an explicit `--force`/re-run flag (FR-008). Partial/interrupted interviews write nothing.
- **Rationale**: Satisfies FR-005/FR-007/FR-008 and SC-003 (< 5 min). Refusing silent overwrite protects hand-edits.
- **Alternatives considered**:
  - *Web form for the interview* — rejected: no web surface in M1 (FastAPI is M5); a CLI prompt is sufficient and simplest.
  - *Re-run interview automatically each run* — rejected: violates FR-008; prefs are user-owned after seeding.

## R6. SQLite store schema and initialization

- **Decision**: `db init` creates `jobs.db` with a `jobs` table matching the HLD data model (§6): `id` (PK, dedup key), `source`, `title`, `company`, `location`, `city`, `country`, `work_mode`, `description`, `employment_type`, `salary`, `apply_url`, `score`, `breakdown` (JSON text), `matched_skills` (JSON text), `reason`, `state` (default `new`), `first_seen`, `last_seen`, `updated_at`. A `schema_version` (via `PRAGMA user_version`) supports later migrations. `CREATE TABLE IF NOT EXISTS` makes init idempotent (FR-011, US3 scenarios).
- **Rationale**: Defining the full shape now (even though M1 doesn't populate it) lets M2–M5 write without redefining the record, and bakes in the idempotency (Constitution IV) and explainability (Constitution V) fields up front. Stdlib `sqlite3` needs no dependency.
- **Alternatives considered**:
  - *Defer schema to M2* — rejected: US3 explicitly scopes establishing the durable store to M1, and defining it now prevents each later milestone inventing ad hoc columns.
  - *An ORM (SQLAlchemy)* — rejected: YAGNI (Constitution VI); a single table with plain `sqlite3` and parameterized queries is simpler and fully testable.
  - *A migration framework (Alembic)* — rejected for M1: `PRAGMA user_version` + a small hand-rolled migration switch is enough at this scale.

## R7. App data directory / file locations

- **Decision**: A single resolved app data directory (default `~/.job-hunter/`, overridable via an env var) holds `profile.json`, `prefs.yaml`, and `jobs.db`. `config.py` centralizes path resolution.
- **Rationale**: Keeps all local state in one predictable, user-inspectable place (Constitution: local-first). Env override eases testing (point at a temp dir).
- **Alternatives considered**: *Current-working-directory files* — rejected: fragile depending on where the CLI is invoked; a fixed home-relative dir is more robust.
