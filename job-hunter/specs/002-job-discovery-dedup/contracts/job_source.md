# Interface Contract: `JobSource`

The pluggable seam that lets a new source (the ATS watchlist, later) join
discovery without changing the orchestrator (FR-002, Constitution VI). Defined in
`src/jobhunter/sources/base.py`.

## Interface

```python
class JobSource(Protocol):
    name: str
    def fetch(self, queries: list[SearchQuery]) -> list[RawPosting]: ...
```

| Member | Contract |
|---|---|
| `name` | Stable, lowercase source identity (`"jsearch"`, `"adzuna"`, later `"ats"`). Used as the `source` column value, the trace `source=` tag, and the summary key. MUST be unique per source. |
| `fetch(queries)` | Issue this source's lookups for the given queries and return raw, source-shaped postings. MUST respect the per-source query budget (bounded requests) and route all HTTP through the shared `http.py` wrapper (caching + 429 backoff). |

## Behavioral requirements

- **Bounded**: `fetch` MUST NOT exceed the configured per-source query budget for
  the run (FR-004); when the budget is reached it stops and returns what it has.
- **Cached**: identical queries within the cache TTL MUST be served from cache,
  not re-fetched (FR-005).
- **Isolated failure**: on an unrecoverable error (network, auth, rate-limit
  after bounded retries, malformed response) `fetch` MUST raise `SourceError`;
  the orchestrator catches it, records a per-source failure, and continues with
  other sources (FR-017). `fetch` MUST NOT call `sys.exit` or swallow-then-return
  partial garbage silently.
- **Credential-gated**: a source missing its required credential reports itself
  as unavailable (raising `SourceError` or excluded before the run) rather than
  crashing the process.
- **Raw, not canonical**: `fetch` returns source-shaped dicts (`RawPosting`);
  mapping to the canonical `Job` is done by the per-source normalizer in
  `discovery/normalize.py`, not by the source.
- **No personal payload**: query params carry only public search terms/locations;
  a source MUST NOT receive or transmit resume/profile/prefs content (FR-021).
- **Traced**: each `fetch` runs inside `obs.trace("source.fetch", source=name)` so
  start/outcome/duration/identity are recorded (metadata only) (FR-020).

## Registration

The orchestrator (`discovery/run.py`) holds the list of active sources (filtered
by `--source` and by available credentials). Adding a source = implement the
Protocol + add it to that list. No other code changes (FR-002).

## Types (see [data-model.md](../data-model.md))

- `SearchQuery` — `{ keywords: str, location: str }`.
- `RawPosting` — an opaque source-shaped dict.
- `SourceError` — raised on unrecoverable source failure.
