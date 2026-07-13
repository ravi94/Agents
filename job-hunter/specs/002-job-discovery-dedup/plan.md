# Implementation Plan: Job Discovery, Normalization & Dedup

**Branch**: `002-job-discovery-dedup` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-job-discovery-dedup/spec.md`

## Summary

M2 turns the empty-but-shaped M1 job store into a living inventory. A single manually-triggered `jobhunter discover` run queries two external aggregators (JSearch, Adzuna India) behind a common `JobSource` interface, normalizes each source's payload into the canonical `Job` shape already defined by the M1 `jobs` schema, deduplicates within the run and against the store by a stable idempotency key, and persists genuinely-new jobs (state `new`, `first_seen` set) while merely refreshing `last_seen` on jobs already seen — the difference between a search and a monitor (Constitution IV). No scoring, hard-filtering, or alerting happens here (FR-025); preferences influence discovery only by shaping the search query.

Technical approach: a deterministic Python package extension under `src/jobhunter/` adding a `sources/` package (the pluggable interface + JSearch/Adzuna adapters) and a `discovery/` package (query derivation, normalization + work-mode classification, dedup, and the run orchestrator). External calls use `httpx` with a bounded-retry/429-backoff wrapper and a small file-based response cache to stay inside free tiers (Constitution II/III). Every source fetch is traced (metadata only) under the M1 run-correlation-id/rotating-log machinery, and the run ends with a per-source summary and an ntfy signal on whole-run failure (Constitution VIII). The M1 store gains a `touch_last_seen` seam so re-seen jobs advance `last_seen` without disturbing `first_seen` or `state`.

## Technical Context

**Language/Version**: Python 3.11+ (matches M1).

**Primary Dependencies**: `httpx` (source HTTP calls — new in this milestone; named in the constitution stack), `pydantic` v2 (canonical `Job` + raw-payload validation, reused), standard-library `sqlite3` (existing store), standard-library `json`/`hashlib`/`pathlib` (response cache), existing `PyYAML` (optional `prefs.search` override). No web framework (FastAPI is M5). **No LLM dependency in this milestone** — resume structuring is M1, re-rank is M3.

**Storage**: The existing M1 SQLite store (`jobs.db`) is the single sink — this milestone writes job rows into it (no new database). A small on-disk response cache lives under a new `cache/` subdirectory of the app data directory. Credentials are read from the environment, never persisted.

**Testing**: `pytest`. TDD is mandatory (Constitution VII). All deterministic logic — query derivation, normalization, work-mode classification, idempotency-key computation, within-run + cross-run dedup, the retry/backoff policy, cache hit/miss, and the run summary — is tested directly. Source adapters are tested against **recorded/fixture JSON payloads** (a fixture `JobSource` and captured JSearch/Adzuna response samples); **no test performs a live API call**.

**Target Platform**: Local macOS (single-user), CLI-invoked, manual trigger (no scheduler — Constitution Scheduling constraint).

**Project Type**: Single Python project (CLI + library), extending the M1 package. No frontend.

**Performance Goals**: Not latency-sensitive. A run issues a bounded handful of requests per source (cache-served on same-day re-runs) and processes hundreds–low-thousands of postings. Correctness and free-tier safety dominate over speed.

**Constraints**: Free-tier only — bounded queries/run, response caching, exponential backoff honoring `Retry-After` on HTTP 429 (Constitution II/III). Per-source isolation: one dead source never fails the run (Resilience). Privacy: only public job-posting data and non-personal query metadata leave the machine; resume/profile/`prefs.yaml` contents are never sent to a source nor written to logs/traces (Constitution I, FR-021).

**Scale/Scope**: Single user, two live sources (interface ready for the ATS watchlist later), one SQLite store. Scoring/alerting/board explicitly out of scope (FR-025).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|---|---|---|
| I. Explicit LLM Provider Boundaries | M2 has **no LLM text-generation touchpoint** (re-rank is deferred to M3) and needs no embeddings. The only external egress is the job-source APIs, carrying public job data + query metadata — no resume/profile/prefs payload (FR-021). | PASS (N/A) |
| II. Bounded Usage, Zero Incremental Cost | Discovery uses aggregator **free tiers** with a bounded per-source query budget, response caching, and 429 backoff (FR-004–006). No metered LLM billing introduced. | PASS |
| III. Ethical Boundaries (NON-NEGOTIABLE) | No LinkedIn scraping — only sanctioned aggregator endpoints (FR-007). Rate limits respected via bounded queries, caching, and backoff (FR-004–006). No auto-apply (nothing here applies). | PASS |
| IV. Monitor, Not Search (Idempotent State) | The heart of this milestone: stable idempotency key (source id, else `title\|company\|city`), `first_seen`/`last_seen`, re-seen jobs update `last_seen` only and never re-alert or reset `state` (FR-012–015). | PASS |
| V. Explainable Ranking | No scoring in M2; the store's `score`/`breakdown`/`matched_skills`/`reason` columns are left null for M3 to populate. No opaque number surfaced. | PASS (N/A) |
| VI. Deterministic Simplicity (YAGNI) | Plain deterministic Python; sources behind a common `JobSource` interface; **no agent framework**. httpx + stdlib only. | PASS |
| VII. Test-First Development (NON-NEGOTIABLE) | Every deterministic unit (normalize, dedup, query, work-mode, backoff, cache, summary) is test-first; source adapters tested via fixtures/mocks — no live call is a pass condition. | PASS |
| VIII. Observable by Default | Reuses the M1 run-id/rotating-log/ntfy infra; adds a trace per source fetch (start/outcome/duration/endpoint — metadata only) and a per-run summary (fetched/new/seen/skipped/per-source failures); ntfy on whole-run failure. | PASS |

**Technology & Operational Constraints**: Stack additions stay within the constitution (`httpx` is explicitly listed). SQLite remains the single source of truth — all job writes go through the store. **Filter-before-score** is honored trivially (no embedding/LLM work occurs in M2; preferences only shape the query, they do not gate). **Resilience** (per-source try/except; partial results valid) is a first-class requirement here (FR-017–018). **Scheduling** stays manual (CLI trigger).

**Result**: PASS — no violations. Complexity Tracking not required.

**Post-design re-check (after Phase 1)**: The data model adds only the `Job`-normalization view over the existing `jobs` columns plus a `touch_last_seen` store seam; contracts add a `discover` CLI command and the `JobSource` interface; no LLM touchpoint, no agent framework, and no new persistent store were introduced. External egress remains job-source APIs with public data only. Idempotency (IV) and the null explainability columns (V) are preserved. Still PASS.

## Project Structure

### Documentation (this feature)

```text
specs/002-job-discovery-dedup/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── cli.md               # `jobhunter discover` command contract
│   ├── job_source.md        # JobSource interface contract
│   └── source_mapping.md    # JSearch/Adzuna payload → canonical Job mapping + work-mode rules
├── checklists/
│   └── requirements.md  # spec quality checklist (from /speckit-specify)
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

```text
src/
└── jobhunter/
    ├── cli.py                 # + `discover` command wired to discovery.run (extends M1)
    ├── config.py              # + cache_dir() path helper (extends M1)
    ├── http.py                # httpx wrapper: bounded retries + 429 backoff (Retry-After)
    ├── models/
    │   └── preferences.py     # + optional `search` block (SearchPrefs) — additive, back-compat
    ├── sources/               # NEW: pluggable discovery sources
    │   ├── __init__.py
    │   ├── base.py            # JobSource protocol/ABC + RawPosting typing + SourceError
    │   ├── cache.py           # file-based response cache (TTL, hashed key) under cache/
    │   ├── jsearch.py         # JSearch adapter (job_is_remote available)
    │   └── adzuna.py          # Adzuna India adapter (work-mode text-inferred)
    ├── discovery/             # NEW: deterministic pipeline over sources
    │   ├── __init__.py
    │   ├── query.py           # derive search queries: profile.roles×prefs.locations, prefs.search override
    │   ├── normalize.py       # raw payload → canonical Job dict + work-mode classification
    │   ├── dedup.py           # idempotency key + within-run/cross-run dedup
    │   └── run.py             # orchestrator: discover→normalize→dedup→persist + run summary
    └── store/
        └── db.py              # + touch_last_seen(id): advance last_seen only (extends M1)

tests/
├── unit/
│   ├── test_query.py              # query derivation (profile+prefs; override; empty→no-op)
│   ├── test_normalize.py          # field mapping + optional-field handling (no fabrication)
│   ├── test_work_mode.py          # remote/hybrid/onsite/unknown classification
│   ├── test_dedup.py              # idempotency key + within-run collapse; new vs seen
│   ├── test_http_backoff.py       # 429 backoff/retry bound; Retry-After honored
│   ├── test_cache.py              # cache hit within TTL; miss after expiry
│   └── test_store_touch_last_seen.py  # last_seen advances; first_seen/state preserved
├── integration/
│   ├── test_discover_run.py       # end-to-end via fixture sources: new/seen counts, summary
│   ├── test_discover_idempotent.py# second run adds zero dups; last_seen bumped
│   └── test_discover_resilience.py# one source raises → run completes; failure in summary
└── fixtures/
    ├── jsearch_response.json       # captured JSearch payload sample
    ├── adzuna_response.json        # captured Adzuna payload sample
    └── source_dupe_pair.json       # same role from both sources (cross-source dedup)
```

**Structure Decision**: Extend the single M1 package rather than start a new project. Two new subpackages give clean seams that honor Constitution VI and the HLD's "ATS watchlist slots in last": `sources/` holds the pluggable `JobSource` interface plus per-source adapters (a future `sources/ats.py` implements the same interface with zero orchestrator change), and `discovery/` holds the deterministic, individually-testable pipeline stages. HTTP concerns (retry/backoff/caching) are isolated in `http.py` + `sources/cache.py` so every adapter inherits free-tier safety uniformly, and the store keeps its role as the single source of truth via a new narrow `touch_last_seen` seam.

## Complexity Tracking

> No Constitution Check violations. Section intentionally empty.
