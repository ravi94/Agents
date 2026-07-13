# Quickstart & Validation: Job Discovery, Normalization & Dedup

End-to-end validation that M2 works. Proves each user story independently.
Details live in [contracts/cli.md](./contracts/cli.md),
[contracts/source_mapping.md](./contracts/source_mapping.md), and
[data-model.md](./data-model.md).

## Prerequisites

- M1 complete and installed (`pip install -e .` from repo root).
- A persisted profile (`jobhunter profile <resume.pdf>`) and a valid
  `prefs.yaml` (`jobhunter prefs init`) under `JOBHUNTER_HOME`.
- Source credentials in the environment for a live run (optional for tests):
  - `JSEARCH_API_KEY` (RapidAPI)
  - `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`
- Optional: `JOBHUNTER_HOME=./.tmp-jobhunter` to keep validation state isolated,
  and `JOBHUNTER_NTFY_TOPIC` to observe the error signal.

## Run the test suite first (TDD gate)

Per Constitution VII, tests are written first and observed to fail, then pass.
All source I/O in tests uses captured fixtures — **no live API call**.

```bash
pytest -q
```

Expect green: unit tests (query derivation, normalization, work-mode
classification, dedup/idempotency-key, 429 backoff, response cache,
`touch_last_seen`) and integration tests (discover run, idempotent re-run,
per-source resilience) all pass against fixture sources.

## Story 1 — Discover and persist new jobs (P1)

```bash
jobhunter discover --dry-run     # inspect what would be stored, writes nothing
jobhunter discover               # real run: persists new jobs
```

**Expect**: a summary printing `fetched / new / seen / skipped` and per-source
outcomes. After the real run, the store holds canonical job rows with `state=new`,
`first_seen`/`last_seen` set, a `work_mode` of remote/hybrid/onsite/unknown, and
null `score`/`breakdown` (scoring is M3). Verify a stored row:

```bash
sqlite3 "$JOBHUNTER_HOME/jobs.db" \
  "select id, source, work_mode, state, first_seen, last_seen from jobs limit 5;"
```

Validates SC-001 (every posting normalized; work-mode always set).

## Story 2 — Re-run without duplicates (monitor semantics, P2)

```bash
jobhunter discover               # first run
jobhunter discover               # second run, same day (cache-served)
```

**Expect**: the second run reports mostly `seen` (not `new`); row **count does
not grow** for repeated postings; each re-seen row's `last_seen` advances while
`first_seen` and `state` are unchanged. Confirm no duplicates and that a job you
manually set to a later state is not reset:

```bash
sqlite3 "$JOBHUNTER_HOME/jobs.db" "select count(*), count(distinct id) from jobs;"
# the two counts are equal → no duplicate ids
```

Validates SC-002. The `test_discover_idempotent` integration test proves the
`last_seen`-only advance mechanically.

## Story 3 — Resilient multi-source discovery (P3)

```bash
# Simulate a dead source by unsetting one credential, then run:
unset ADZUNA_APP_KEY
jobhunter discover
```

**Expect**: the run **completes with exit 0**, stores the healthy source's new
jobs, and lists the unavailable/failed source in the summary (not a crash).
Cross-source dedup: a role returned by both sources is stored once — proven by
`test_discover_resilience` and the `source_dupe_pair.json` fixture.

Validates SC-003 (partial failure tolerated) and SC-004 (cross-source single record).

## Free-tier & privacy checks

```bash
jobhunter discover               # first run (populates cache)
jobhunter discover               # within TTL → served from cache
```

**Expect**: the second run issues no new external requests for identical queries
(cache hit; SC-006), and per-source request counts never exceed the configured
budget. Inspect the run log to confirm no personal data leaked (SC-007):

```bash
grep -iE 'skill|resume|salary_expectation|prefs' "$JOBHUNTER_HOME/logs/jobhunter.log"
# expect no matches from resume/profile/prefs content — only public job + metadata
```

Each source fetch appears as a traced `start/ok|fail source=<name> duration_ms=…`
line under the run's correlation id.

## Success criteria mapping

| Criterion | Validated by |
|---|---|
| SC-001 every posting normalized, work-mode set | Story 1 + `select` check |
| SC-002 no duplicates, last_seen advances, first_seen/state preserved | Story 2 + `count` check |
| SC-003 partial-failure run still succeeds | Story 3 (dead source) |
| SC-004 cross-source single record | Story 3 + dupe fixture |
| SC-005 per-run summary + run-id on every log line | run summary + log inspection |
| SC-006 bounded requests, cache hit within TTL | free-tier check |
| SC-007 no personal data in logs/requests | privacy grep |
