# CLI Contract: M4 Run Command

M4 adds one command to the `jobhunter` CLI. State lives under the app data
directory (default `~/.job-hunter/`, overridable via `JOBHUNTER_HOME`). This
command introduces no new endpoint or store — it composes the existing
`discover` (M2) and `score` (M3) stages into one invocation.

## `jobhunter run [--source NAME]... [--dry-run] [--rerank]`

Run the whole pipeline end to end in one command: discover → normalize → dedup →
persist (M2), then filter → score → persist → alert (M3), under one shared run
id, ending with one combined summary (User Stories 1–4).
Manually triggered; **no scheduler** (Constitution Scheduling — launchd is a
later fast-follow).

| Aspect | Contract |
|---|---|
| Prerequisites | A persisted `profile.json` and valid `prefs.yaml` exist (same preconditions as `discover`/`score`); the store exists (`db init` or auto-created). |
| Behavior | Calls `run_discovery(sources, ...)` then `run_scoring(...)` in that order, within the single process run id. Discovery persists new jobs; scoring then filters/scores every `state='new'` job (this run's finds + prior unscored leftovers) and alerts on genuinely-new high scorers. Returns a combined summary. |
| `--source NAME` | Repeatable. Restrict discovery to the named source(s) (`jsearch`, `adzuna`); default = all configured sources. Mirrors `discover --source`. Scoring is unaffected by this flag (it scores whatever is `new`). |
| `--dry-run` | Rehearse the full pipeline: fetch/normalize/dedup/filter/score/alert are computed and summarized, but **nothing is written** to the store and **no notification is sent** — propagated to *both* stages. |
| `--rerank` | After scoring, send the top ~25 `scored` survivors through one bounded LLM call for a qualitative `reason`. Omitted by default — the pipeline never calls a text-generation LLM otherwise. Same semantics as `score --rerank`. |
| Success output | One combined per-run summary to stdout: the discovery block (per-source ok/failed, `fetched`/`new`/`seen`/`skipped`) and the scoring block (`filtered_out`/`scored`/`alerted`/`reranked`, plus this run's top contributor). Exit code `0`. |
| Source failure | A single discovery source failing is isolated (recorded in the discovery block as `failed <reason>`); the run continues, scoring still runs, and the command still exits `0`. |
| All sources fail | Discovery reports zero new jobs with per-source failures noted; scoring still runs over any pre-existing `state='new'` jobs; exit `0`. |
| Missing profile/prefs | Fails fast with an actionable stderr error before any external work; exits non-zero and fires an ntfy error signal (existing `main()` handler). |
| Missing notification channel | If `JOBHUNTER_NTFY_TOPIC` is unset, the run still completes and persists; only alert/error sends are skipped. |
| Local embeddings unavailable | Scoring's `scope` component falls back to keyword overlap for that run (inherited from M3); the run still completes and exits `0`. |
| Re-rank failure | An errored/timed-out `--rerank` call does not affect persisted scores/alerts; exit `0`, only the qualitative `reason` is absent (inherited from M3). |
| Whole-run failure | Only an unexpected error that prevents completion (e.g. store unwritable) exits non-zero and fires an ntfy error signal, per the existing M1–M3 pattern. |
| Idempotency | Re-running `run` never re-alerts an already-alerted role and never rescores a role past `new`; two runs over the same above-threshold role alert exactly once total (Constitution IV). |

### Environment / configuration

| Variable | Purpose |
|---|---|
| `JOBHUNTER_NTFY_TOPIC` | (M1) ntfy topic; used for both new-high-scorer alerts (M3) and whole-run error signals. Absent → sends skipped, run still completes. |
| `JOBHUNTER_HOME` | (M1) app data dir override. |
| Source API keys (M2) | Whatever the selected discovery sources require; a missing/invalid key surfaces as that source's isolated failure, not a whole-run abort. |
| *(local, no env var)* Ollama endpoint | Assumed at its default local address; not user-configurable in v1 (Constitution I). |

### Example output (shape, not exact wording)

```
Pipeline run <run-id> complete.
  discovery: fetched: 42   new: 18   seen: 22   skipped: 2
    sources:
      jsearch  ok
      adzuna   failed  HTTP 429 rate limited
  scoring:   filtered_out: 6   scored: 12   alerted: 2   reranked: 0
    top: 'Staff Backend Engineer' — <top contributing factor>
```

With `--dry-run` the same shape prints, prefixed/annotated to make clear nothing
was written (e.g. a `(dry run — no writes, no alerts)` note), and the store is
unchanged.

## Cross-cutting

- Errors are actionable and printed to stderr; the combined run summary goes to
  stdout.
- The command writes only into the existing single `jobs.db` (single source of
  truth) plus the outbound ntfy pushes the composed stages already make.
- No schema change, no new store, no new dependency, no scheduler — this command
  is a composition of `discover` + `score`.
- The FastAPI triage/tracker board and automatic scheduling remain out of scope
  (later milestones).
