# CLI Contract: M2 Discovery Command

M2 adds one command to the `jobhunter` CLI. State lives under the app data
directory (default `~/.job-hunter/`, overridable via `JOBHUNTER_HOME`). This
command is the first to make outbound network calls to job sources.

## `jobhunter discover [--source NAME]... [--dry-run]`

Run one discovery pass: query sources, normalize, dedup, and persist new jobs
(User Stories 1–3). Manually triggered; no scheduler (Constitution Scheduling).

| Aspect | Contract |
|---|---|
| Prerequisites | A persisted `profile.json` (M1 `profile`) and a valid `prefs.yaml` (M1 `prefs init`) exist; the store exists or is created on demand (reuses M1 `init_db`). |
| Behavior | Derive queries (profile roles × prefs locations, or `prefs.search` override) → for each configured source, fetch (bounded, cached, 429-backoff) → normalize + classify work mode → dedup within-run and vs store → insert new (`state=new`, `first_seen`) / advance `last_seen` on already-seen. |
| `--source NAME` | Restrict the run to the named source(s) (e.g. `--source jsearch`). Repeatable. Default: all configured sources. |
| `--dry-run` | Fetch + normalize + dedup and report the summary, but **write nothing** to the store (for safe inspection). |
| Success output | A per-run summary to stdout: `fetched`, `new`, `seen`, `skipped`, and per-source outcomes (incl. failures). Exit code `0`. |
| Partial success | If some sources fail but at least the run completes, exit `0`; failed sources are listed in the summary (FR-017/018). |
| Missing credential | A source lacking its env credential is skipped and reported as unavailable; not a run failure. |
| No usable query | If neither profile nor prefs yields search terms, do nothing external, log the reason, print a zero summary. Exit `0` (edge case). |
| Whole-run failure | Only an unexpected error that prevents completion (e.g. store unwritable) exits non-zero and fires an ntfy error signal (FR-024). |
| Privacy | Only public job data + query metadata leave the machine; resume/profile/prefs contents are never sent to a source nor logged (FR-021). |
| Idempotency | A re-run adds zero duplicates; already-seen jobs get `last_seen` advanced with `first_seen`/`state` unchanged (FR-013–015). |

### Environment / configuration

| Variable | Purpose |
|---|---|
| `JSEARCH_API_KEY` | RapidAPI key for the JSearch source. Absent → JSearch skipped. |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Adzuna India credentials. Absent → Adzuna skipped. |
| `JOBHUNTER_NTFY_TOPIC` | (M1) ntfy topic for error signals; absent → no push. |
| `JOBHUNTER_HOME` | (M1) app data dir override. |

### Example output (shape, not exact wording)

```
Discovery run <run-id> complete.
  fetched: 42   new: 11   seen: 30   skipped: 1
  sources:
    jsearch  ok      fetched=25  (budget 5 queries)
    adzuna   failed  rate-limited after 3 retries
```

## Cross-cutting

- Errors are actionable and printed to stderr; the run summary goes to stdout.
- The command writes only into the existing single `jobs.db` (single source of truth).
- No scoring, hard-filtering, or alerting is performed (FR-025) — those are M3/M4.
