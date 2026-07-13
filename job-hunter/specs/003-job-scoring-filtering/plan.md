# Implementation Plan: Job Scoring, Filtering & Alerting

**Branch**: `003-job-scoring-filtering` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-job-scoring-filtering/spec.md`

## Summary

M3 turns the M2 inventory of raw `state=new` jobs into a ranked, explainable,
alert-worthy shortlist. For every `new` job: cheap hard filters (location,
work mode, company type, comp/seniority floor) from `prefs.yaml` gate it first
— failures become `state=filtered_out` with a reason, never scored. Survivors
get a composite score from `prefs.yaml` soft weights against `profile.json`
skills/experience, with the full per-component breakdown and matched skills
persisted alongside the score (never a bare number, Constitution V). A job
that is both genuinely new and scores at/above the configured threshold
triggers exactly one ntfy notification, ever (Constitution IV) — tracked by a
new `alerted_at` column so reruns and later prefs edits can never re-alert.
An opt-in `--rerank` pass sends the top ~25 survivors through one bounded
Claude call for a qualitative fit reason, without being a precondition for
anything else in the pipeline.

Technical approach: a new `scoring/` package (filter gate, composite scorer,
optional re-rank, alert dispatch, and a run orchestrator mirroring M2's
`discovery/run.py` shape) plus a `jobhunter score` CLI command. Scoring's
`scope` component is the project's first consumer of Constitution I's
"embeddings always run locally via Ollama" commitment: a local
`mxbai-embed-large` call (via the existing `httpx` dependency, no new HTTP
client) produces the semantic skill/role match, combined with NumPy
(newly added — already named in the constitution's stack) for cosine
similarity; `comp`/`stability`/`work_life_balance` stay plain deterministic
Python. The one schema change — a nullable `alerted_at` column, `jobs`
schema bumped to version 2 — is applied idempotently by `init_db`, exactly
as M1 established. Alerting reuses the existing `obs` ntfy integration point
rather than adding a new channel.

## Technical Context

**Language/Version**: Python 3.11+ (matches M1/M2).

**Primary Dependencies**: `pydantic` v2 (reused — `Preferences`/`Profile`
already carry the `HardFilters`/`SoftWeights`/`Alerting` shapes this
milestone consumes), standard-library `sqlite3` (existing store, one additive
column), `httpx` (reused — now also calls the local Ollama embeddings
endpoint), **`numpy`** (NEW — cosine similarity for the `scope` score
component; already named in the constitution's technology stack but not yet
a dependency of any prior milestone), the existing `LLMProvider` seam
(extended with one new method for the optional re-rank, implemented by the
existing `ClaudeCLIProvider`). No web framework (FastAPI is a later
milestone), no new HTTP client library.

**Storage**: The existing M1/M2 SQLite store (`jobs.db`) remains the single
sink. One additive, nullable column (`alerted_at`) is added via an idempotent
`ALTER TABLE`, bumping `SCHEMA_VERSION` to `2`; no new table, no new database.

**Testing**: `pytest`. TDD is mandatory (Constitution VII). All deterministic
logic — hard filters (including missing-data pass-through per dimension),
the composite scoring math and its component functions, the schema migration,
and the alert-threshold/no-double-alert logic — is tested directly with
fixture jobs/profiles/prefs. The embeddings call and the optional LLM re-rank
are tested against the **provider/HTTP boundary** (mocked Ollama responses,
mocked `LLMProvider`), per Constitution VII's guidance for LLM-touching code:
tests assert on contract/shape and error handling, never exact model output,
and no test depends on a live Ollama or Claude call.

**Target Platform**: Local macOS (single-user), CLI-invoked, manual trigger
(no scheduler — Constitution Scheduling constraint). Assumes a local Ollama
instance at its default address when `--rerank`-independent embeddings are
used; degrades to a deterministic fallback when Ollama is unreachable.

**Project Type**: Single Python project (CLI + library), extending the M1/M2
package. No frontend (the triage board is a later milestone).

**Performance Goals**: Not latency-sensitive. A run processes the jobs
currently `state=new` from the store (bounded by discovery's own free-tier
query budget, so low hundreds at most per run); the one embeddings call per
job plus at most one re-rank call per run keep cost proportional to relevant
volume (Constitution "Filter before score").

**Constraints**: Filter-before-score is structural, not incidental — hard
filters run before any embedding/LLM work, so cost never scales with jobs
that were never going to qualify. Embeddings MUST stay local (Ollama,
`mxbai-embed-large`) regardless of which text-generation provider is active
(Constitution I). Re-rank is optional, bounded to ~25 survivors, and
manually opted into per run (Constitution II). Alerting MUST fire at most
once per job, ever (Constitution IV). Every scored job MUST carry its full
breakdown — no opaque numbers (Constitution V).

**Scale/Scope**: Single user, one SQLite store, one local embeddings
endpoint, one optional LLM re-rank call per run. The web triage board and any
tracking states beyond `new`/`filtered_out`/`scored` are explicitly out of
scope (see spec Assumptions) and deferred to a later milestone.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|---|---|---|
| I. Explicit LLM Provider Boundaries | Two touchpoints, both bounded and swappable: embeddings (mandatory local Ollama `mxbai-embed-large`, no cloud alternative per Principle I) and the optional re-rank (reuses the existing `LLMProvider` seam; only job title/description/matched-skills + profile skills/roles cross the boundary — never `prefs.yaml` or tracking state). | PASS |
| II. Bounded Usage, Zero Incremental Cost | Re-rank is opt-in (`--rerank`), capped at ~25 survivors, one call per run, manually triggered — never continuous or per-job-independent. Embeddings run locally (zero cost, no shared quota). | PASS |
| III. Ethical Boundaries (NON-NEGOTIABLE) | No auto-apply; nothing here applies to a role or scrapes a source — this milestone only reads/scores jobs already in the store. | PASS (N/A) |
| IV. Monitor, Not Search (Idempotent State) | `alerted_at` is written exactly once per job and never reset — a rescored or reprocessed job never re-alerts (FR-009). Rescoring only ever touches `state='new'` jobs; anything already `filtered_out`/`scored`/user-set is left untouched (FR-013). | PASS |
| V. Explainable Ranking | This milestone's core purpose: every `score` is written together with its full `breakdown` (per-component scores + matched skills), never alone; inferred/proxy components (`stability`, `work_life_balance`) are explicitly labeled as such, never presented as direct measurement. | PASS |
| VI. Deterministic Simplicity (YAGNI) | Filtering and three of four score components are plain deterministic Python; the fourth (`scope`) is a pure-function embedding lookup, not an agent/LLM-reasoning step. Re-rank is the only reasoning-LLM touchpoint and is optional. No agent framework introduced. | PASS |
| VII. Test-First Development (NON-NEGOTIABLE) | Hard filters, scoring math, migration, and alert-dedup logic are tested first as deterministic units; the embeddings call and re-rank provider are tested via mocked contracts/error-handling, never exact wording, and no test requires a live Ollama/Claude call. | PASS |
| VIII. Observable by Default | Reuses the M1/M2 run-id/rotating-log/ntfy infra; traces the embeddings call and the re-rank call (metadata only — text length/duration/outcome, never payload content); per-run summary (`filtered_out`/`scored`/`alerted`/`reranked`); ntfy now also carries genuine alerts, not just run failures. | PASS |

**Technology & Operational Constraints**: `numpy` addition is explicitly
sanctioned by the constitution's declared stack. **Filter before score** is
the literal shape of the pipeline (FR-001 gates before any scoring work).
SQLite remains the single source of truth — the one schema change is an
additive, idempotent column, applied the same way M1 already established.
**Scheduling** stays manual (CLI trigger, `jobhunter score`).

**Result**: PASS — no violations. Complexity Tracking not required.

**Post-design re-check (after Phase 1)**: The data model adds one nullable
column (`alerted_at`) and populates the columns M1 already reserved
(`score`/`breakdown`/`matched_skills`/`reason`) — no new persistent store.
Contracts add the `jobhunter score` CLI command and a scoring-algorithm
contract; the only LLM-provider-interface change is one new optional method
reusing the existing seam. Idempotent alerting (IV) and mandatory breakdown
persistence (V) are both enforced at the data-model level (score and
breakdown written together; `alerted_at` write-once). Still PASS.

## Project Structure

### Documentation (this feature)

```text
specs/003-job-scoring-filtering/
├── plan.md                      # This file
├── research.md                  # Phase 0 output
├── data-model.md                # Phase 1 output
├── quickstart.md                # Phase 1 output
├── contracts/                   # Phase 1 output
│   ├── cli.md                       # `jobhunter score` command contract
│   └── scoring_algorithm.md         # hard-filter + composite-score contract
├── checklists/
│   └── requirements.md          # spec quality checklist (from /speckit-specify)
└── tasks.md                     # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

```text
src/
└── jobhunter/
    ├── cli.py                 # + `score` command (extends M1/M2)
    ├── models/
    │   └── preferences.py     # unchanged — HardFilters/SoftWeights/Alerting already present (M1)
    ├── llm/
    │   ├── provider.py        # + abstract `rerank(candidates, profile)` method (extends M1 seam)
    │   └── claude_cli.py      # + rerank() implementation (extends M1)
    ├── obs.py                 # + generalized notify() used by notify_error and the new alert path
    ├── embeddings/            # NEW: local Ollama embeddings client
    │   ├── __init__.py
    │   └── ollama.py          # embed(text) -> vector via local mxbai-embed-large; timeout -> None
    ├── scoring/                # NEW: deterministic filter + score + alert pipeline
    │   ├── __init__.py
    │   ├── filters.py          # hard-filter gate (location/work_mode/company_type/comp/seniority)
    │   ├── scorer.py           # composite score + ScoreBreakdown + matched_skills
    │   ├── rerank.py           # optional bounded top-~25 LLM re-rank orchestration
    │   ├── alert.py            # threshold check + alerted_at write-once + ntfy send
    │   └── run.py              # orchestrator: filter→score→alert→(rerank) + ScoreRunSummary
    └── store/
        └── db.py               # + alerted_at column + migration (SCHEMA_VERSION 1 -> 2)

tests/
├── unit/
│   ├── test_filters.py             # each hard-filter dimension + missing-data pass-through
│   ├── test_scorer.py              # component math, weighting (no renormalization), breakdown shape
│   ├── test_embeddings_ollama.py   # mocked HTTP: success, timeout/unreachable -> fallback signal
│   ├── test_rerank.py              # mocked LLMProvider: bounded to ~25, failure doesn't break run
│   ├── test_alert.py               # threshold gating; alerted_at write-once; no re-alert on rerun
│   └── test_store_alerted_at.py    # migration idempotency; write-once semantics at the store layer
└── integration/
    ├── test_score_run.py               # end-to-end via fixture jobs: filtered/scored/alerted counts
    ├── test_score_rerun_no_realert.py  # second run over already-processed jobs alerts zero
    └── test_score_rerank_optional.py   # --rerank bounded to top ~25; omitted leaves pipeline intact
```

**Structure Decision**: Extend the single M1/M2 package rather than start a
new project, matching M2's own precedent. `embeddings/` is a new, narrow
package isolating the one local-network dependency this milestone
introduces (mirrors how M2 isolated `sources/`) — a future swap of the
embedding model or a richer client stays inside this one file. `scoring/`
mirrors `discovery/`'s shape (one stage per file, one orchestrator) so the
two pipelines read consistently. The `llm/` and `store/` extensions are
additive to existing M1 seams rather than parallel new mechanisms,
consistent with Constitution VI (no duplicated abstractions for the same
underlying concern).

## Complexity Tracking

> No Constitution Check violations. Section intentionally empty.
