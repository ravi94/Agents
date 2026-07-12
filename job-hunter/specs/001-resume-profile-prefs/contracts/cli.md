# CLI Contract: M1 Commands

M1 exposes three commands on the `jobhunter` CLI. All state lives under the app data directory (default `~/.job-hunter/`, overridable via `JOBHUNTER_HOME`).

## `jobhunter profile <resume.pdf>`

Derive and persist the structured profile from a resume PDF (User Story 1).

| Aspect | Contract |
|---|---|
| Input | Path to a text-extractable PDF. |
| Behavior | Extract text (`pypdf`) → structure via `LLMProvider` → validate → atomically write `profile.json`. |
| Success output | Prints a summary (skills count, seniority, roles) and the path written. Exit code `0`. |
| Replace | If `profile.json` exists, it is fully superseded (FR-004). |
| Failure: unreadable/empty PDF | Clear error naming the problem; **no LLM call, no write**; existing profile untouched (FR-012). Exit code non-zero. |
| Failure: provider error/malformed JSON | Clear error; existing profile untouched. Exit code non-zero. |
| Privacy | Only resume text is sent to the provider (FR-014, Constitution I). |

## `jobhunter prefs init [--force]`

Run the one-time guided interview and write `prefs.yaml` (User Story 2).

| Aspect | Contract |
|---|---|
| Behavior | Ask the fixed question set → write `prefs.yaml` in the [prefs schema](./prefs.schema.md) shape. |
| Already exists | Refuse and exit non-zero unless `--force` is passed (protects hand-edits, FR-008). |
| Interrupted | If the user aborts before completion, **nothing is written** (edge case). |
| Success output | Path written + reminder that the file is hand-editable. Exit code `0`. |
| Non-goal | Does NOT run automatically on other commands; seeding only (FR-007). |

## `jobhunter prefs validate` *(also invoked implicitly by any command that reads prefs)*

Validate `prefs.yaml` against the schema.

| Aspect | Contract |
|---|---|
| Valid | Exit `0`; on weight-sum drift, print a **warning** but pass (value preserved, FR-008). |
| Invalid | Exit non-zero with a message naming the offending field and why (FR-013). |

## `jobhunter db init`

Create the SQLite job store if absent (User Story 3).

| Aspect | Contract |
|---|---|
| Behavior | `CREATE TABLE IF NOT EXISTS jobs (...)` + set `PRAGMA user_version`. |
| Idempotent | Existing store and rows reused, never wiped (FR-011, US3 scenarios 1–2). |
| Success output | Path to `jobs.db` and schema version. Exit code `0`. |
| Round-trip guarantee | A written job record reads back with all fields unchanged (US3 scenario 3). |

## Cross-cutting

- All commands resolve paths through the app data directory; `JOBHUNTER_HOME` overrides it (eases testing).
- Errors are actionable and printed to stderr; success summaries to stdout.
- No command performs job discovery, scoring, or network calls other than `profile`'s single provider call.
