# Phase 0 Research: Job Discovery, Normalization & Dedup

All Technical Context unknowns are resolved below. The spec's one scope-affecting
ambiguity (search-term source) was decided during `/speckit-specify`
(profile-derived default, optional `prefs.search` override) and is carried here.

---

## 1. HTTP client & rate-limit handling

**Decision**: Use `httpx` (sync client) behind a thin `http.py` wrapper that
enforces a bounded retry policy with exponential backoff, honoring the
`Retry-After` header on HTTP 429; a small fixed cap on total attempts, after
which the source is reported as a per-source failure.

**Rationale**: `httpx` is already named in the constitution's stack. A single
wrapper gives every source adapter identical free-tier safety (Constitution
II/III) without each re-implementing backoff. Sync (not async) keeps the
pipeline deterministic and simple (Constitution VI) — runs are manual and issue
only a handful of requests, so concurrency buys nothing.

**Alternatives considered**:
- `requests` — not in the stack; httpx is the sanctioned choice.
- `urllib` (stdlib, as `obs._post` uses) — workable but no connection reuse,
  timeouts, or ergonomic header handling; not worth the friction for real API calls.
- `tenacity` for retries — an extra dependency for a ~15-line loop; rejected (YAGNI).
- async httpx + `asyncio.gather` across sources — rejected: adds nondeterminism
  and complexity for no latency benefit at this scale.

---

## 2. Response caching (free-tier protection)

**Decision**: A file-based cache under a new `cache/` subdirectory of the app
data directory. Cache key = a hash of `(source, endpoint, normalized query
params)`; value = the raw JSON response plus a stored timestamp. A hit within a
bounded TTL (default ~6 hours) is served without an external call; misses/expiry
re-fetch and rewrite.

**Rationale**: Same-day re-runs (the expected usage while proving the spine)
must not burn free-tier quota (FR-005, SC-006). File-based + stdlib (`hashlib`,
`json`, `pathlib`) keeps it zero-dependency and local-first (Constitution II/VI),
and inspectable for debugging. TTL is generous because postings churn slowly.

**Alternatives considered**:
- `requests-cache`/`hishel` — extra dependency for behavior a few stdlib lines cover.
- SQLite cache table in `jobs.db` — conflates the store (jobs source-of-truth)
  with transient HTTP cache; keep them separate.
- In-memory only — lost between CLI invocations, so same-day re-runs wouldn't
  benefit; rejected.

Cache entries carry no personal data (only query params + public responses),
consistent with FR-021.

---

## 3. `JobSource` interface shape

**Decision**: A minimal interface (ABC/`Protocol`) each source implements:
- `name: str` — stable source identity (`"jsearch"`, `"adzuna"`, later `"ats"`).
- `fetch(queries: list[SearchQuery]) -> list[RawPosting]` — issues the source's
  bounded requests and returns raw, source-shaped postings (dicts). Raises
  `SourceError` on unrecoverable failure; the orchestrator isolates it.

Normalization is **not** the source's job — each source returns raw payloads and
a per-source normalizer (in `discovery/normalize.py`) maps them to the canonical
`Job`. This keeps adapters thin and mapping logic centrally testable.

**Rationale**: Matches the HLD's "pluggable `JobSource` interface so the ATS
watchlist slots in last" and Constitution VI. A future `sources/ats.py`
implements the same two members with no orchestrator change (FR-002).

**Alternatives considered**:
- Sources return already-canonical `Job`s — spreads mapping across adapters and
  makes normalization rules harder to test uniformly; rejected.
- A fat interface (pagination, auth, backoff as abstract methods) — over-designed
  for two sources; shared HTTP concerns live in `http.py`/`cache.py` instead.

---

## 4. Source APIs, credentials & query derivation

**Decision**:
- **JSearch** (RapidAPI "Google for Jobs" aggregate): key from
  `JSEARCH_API_KEY` (RapidAPI key header). Exposes `job_is_remote` → reliable
  remote signal.
- **Adzuna** (India endpoint): `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` query params.
  No explicit remote flag → work mode is text-inferred.
- Credentials are read from the environment at run time, never written to disk,
  logs, or traces. A missing credential disables that source (logged, counted as
  unavailable) rather than crashing the run.
- **Query derivation** (`discovery/query.py`): default queries are the Cartesian
  product of `profile.roles` (falling back to a coarse term from `profile.seniority`
  if roles are empty) × `prefs.hard_filters.locations`, capped by the per-source
  query budget. If `prefs.search.keywords` is present it **replaces** the
  profile-derived keywords (locations still apply). If neither yields terms, the
  run is a clean no-op (edge case / FR-003).

**Rationale**: These are the two aggregators named in the HLD with the best India
coverage. Env-var credentials keep secrets out of the repo and store
(Constitution privacy). Query derivation implements the confirmed spec decision.

**Alternatives considered**:
- Hard-coding a query string — ignores the user's actual profile/prefs; rejected.
- Adding required search config to `prefs.yaml` — would break existing M1
  prefs files; the override is **optional** and additive instead (back-compat).

---

## 5. Work-mode classification

**Decision**: Deterministic, per-source, testable:
1. If the source gives an explicit remote flag (JSearch `job_is_remote == true`)
   → `remote`.
2. Else infer from title/description text with a small keyword ruleset:
   "remote"/"work from home"/"wfh" → `remote`; "hybrid" → `hybrid`;
   "onsite"/"in office"/"on-site" → `onsite`.
3. If nothing matches → `unknown` (never guessed as a specific mode).

**Rationale**: Honors FR-009/edge case — an explicit signal wins, inference is
best-effort, and `unknown` is a first-class honest outcome (Constitution V spirit:
no fabricated signal). Pure string logic → trivially unit-testable (Constitution
VII).

**Alternatives considered**:
- LLM/embedding classification — violates "no LLM in M2" and Constitution VI;
  rejected. (A future re-rank milestone may refine, but not here.)
- Treating missing signal as `onsite` — fabricates a fact; rejected.

---

## 6. Idempotency key & dedup

**Decision**: `id = source_job_id` when the source provides a stable identifier;
otherwise a normalized `title|company|city` composite (lowercased, trimmed,
whitespace-collapsed). Dedup runs in two places:
- **Within a run**: collapse postings sharing an `id` (including the *same role
  from two different sources* — cross-source dedup) to one record, keeping the
  richer/earlier one deterministically.
- **Across runs**: before insert, look up the `id` in the store; **new** →
  `upsert_job` (state `new`, `first_seen` stamped); **existing** →
  `touch_last_seen(id)` only.

**Rationale**: This is Constitution IV made concrete and matches the HLD dedup
rule exactly. Normalizing the composite prevents trivial-formatting misses.

**Cross-source key note**: A role posted to both JSearch and Adzuna usually has
*different* source ids, so it collapses via the `title|company|city` fallback,
not the source id. The normalizer therefore computes the fallback composite for
every posting and prefers the source id only when it is genuinely stable — see
`source_mapping.md`.

**Alternatives considered**:
- Fuzzy/similarity dedup — nondeterministic, over-engineered for v1; rejected
  (a v2 concern). Exact normalized-key match is predictable and testable.

---

## 7. Store extension: `touch_last_seen`

**Decision**: Add `touch_last_seen(id, path=None)` to `store/db.py`: advances
`last_seen` for an existing row and leaves `first_seen`, `state`, `updated_at`,
and all content columns untouched; a no-op if the id is absent. The M1
`upsert_job` is reused unchanged for the **new-job** path.

**Rationale**: M1's `upsert_job` refreshes every supplied column plus
`updated_at` on conflict — correct for content updates, but re-seeing a posting
is not a content change: FR-015 requires advancing only `last_seen` and never
resetting a later state (e.g. `interested`) back toward `new`. A narrow dedicated
seam expresses that intent precisely and keeps the store the single writer of
audit timestamps. `updated_at` is deliberately *not* bumped on a pure re-sighting
so it continues to mean "content last changed".

**Alternatives considered**:
- Reuse `upsert_job` for re-seen jobs — would overwrite normalized content and
  bump `updated_at` every run, muddying "changed" vs "seen again"; rejected.
- A generic `update_fields` — broader surface than needed; the narrow seam is
  clearer and safer (YAGNI).

---

## 8. Observability wiring

**Decision**: Reuse M1 `obs.py` wholesale. In `main()`, the existing
`configure_run_logging()` already mints the run id and rotating handler — the
`discover` handler adds nothing new there. Each source `fetch` is wrapped in
`obs.trace("source.fetch", source=<name>)`; cache hits/misses log at debug. The
orchestrator logs a structured per-run summary line at run end (fetched / new /
seen / skipped / per-source failures). Whole-run failure raises `CommandError`,
which `main()` already routes to `notify_error` (ntfy). A single dead source is
logged + traced + counted, never escalated to a run failure (FR-017/024).

**Rationale**: Constitution VIII satisfied with zero new infra (Principles
II/VI). Traces stay metadata-only — operation, source name, duration, outcome —
never query payloads that could embed personal terms (FR-021); `obs.trace`
already logs only the exception *type* on failure.

**Alternatives considered**:
- A hosted tracer (Phoenix, etc.) — constitution allows only as an opt-in dev
  aid, never a runtime dependency; not used.

---

## 9. Testing strategy (no live calls)

**Decision**: Source adapters are exercised against captured fixture JSON
(`tests/fixtures/jsearch_response.json`, `adzuna_response.json`) via an injected
transport/fixture `JobSource`; integration tests drive `discovery/run.py` with
fixture sources (one healthy, one raising) against a temp `JOBHUNTER_HOME` store.
No test hits a real endpoint or requires credentials. Deterministic units
(normalize, work-mode, dedup, query, backoff, cache, `touch_last_seen`) are
tested directly, test-first (Constitution VII).

**Rationale**: Live APIs are flaky, rate-limited, and credential-gated — unfit as
a pass condition (mirrors the M1 rule for LLM calls). Fixtures make the mapping
and monitor semantics verifiable and stable.

**Alternatives considered**:
- VCR-style cassette libraries — extra dependency; hand-captured fixtures suffice
  for two sources.
