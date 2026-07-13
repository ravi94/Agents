# CLI Contract: M3 Scoring Command

M3 adds one command to the `jobhunter` CLI. State lives under the app data
directory (default `~/.job-hunter/`, overridable via `JOBHUNTER_HOME`). This
command is the first to call a local Ollama endpoint (embeddings) and,
optionally, the second to call the LLM provider (re-rank).

## `jobhunter score [--dry-run] [--rerank]`

Run one scoring pass over every job currently in `state='new'`: hard-filter
gate → composite score + breakdown → alert on genuinely-new high scorers →
optional bounded LLM re-rank of the top ~25 survivors (User Stories 1–4).
Manually triggered; no scheduler (Constitution Scheduling).

| Aspect | Contract |
|---|---|
| Prerequisites | A persisted `profile.json` and valid `prefs.yaml` exist (same preconditions as `discover`); the store exists (`db init` or auto-created). |
| Behavior | For every `state='new'` job: apply hard filters (`hard_filters.*`) → jobs failing any filter become `state=filtered_out` with `reason` naming the failed filter(s); jobs passing all filters get a composite `score` + `breakdown` + `matched_skills` and become `state=scored`. Then: any `scored` job with `alerted_at IS NULL` and `score >= alerting.score_threshold` gets exactly one ntfy notification and `alerted_at` stamped, up to `alerting.max_alerts_per_run` per run. |
| `--dry-run` | Compute filters/scores/alerts and report the summary, but **write nothing** to the store (for safe inspection) — mirrors `discover --dry-run`. |
| `--rerank` | After scoring, send the top ~25 `scored` survivors (by `score`, this run only) through a single bounded LLM call; each gets a qualitative `reason` appended to its breakdown. Omitted by default — base scoring never calls an LLM. |
| Success output | A per-run summary to stdout: `filtered_out`, `scored`, `alerted`, and `reranked` (0 if `--rerank` not passed). Exit code `0`. |
| Already-processed jobs | Jobs not in `state='new'` (already `filtered_out`, `scored`, or a later user-set state) are left untouched — a rescoring run only ever processes jobs currently `new` (FR-013/FR-014). |
| Missing notification channel | If `JOBHUNTER_NTFY_TOPIC` is unset, scoring/filtering still completes and persists; only the notification send is skipped (FR-010). |
| Local embeddings unavailable | If the local Ollama endpoint is unreachable, the `scope` score component falls back to deterministic keyword overlap for that run (logged); the run still completes and persists scores — never a run failure. |
| Re-rank failure | A `--rerank` call that errors or times out MUST NOT affect already-persisted scores/alerts — the run still exits `0`; only the qualitative `reason` is absent for that run. |
| Whole-run failure | Only an unexpected error that prevents completion (e.g. store unwritable) exits non-zero and fires an ntfy error signal, per the existing M1/M2 pattern. |
| Idempotency | Rerunning `score` with no new `new` jobs is a no-op (`filtered_out=0 scored=0 alerted=0`); a job already alerted on never alerts again regardless of subsequent scores (FR-007/FR-009). |

### Environment / configuration

| Variable | Purpose |
|---|---|
| `JOBHUNTER_NTFY_TOPIC` | (M1) ntfy topic; also used for the new-high-scoring-job alert, not just error signals. Absent → alerts skipped, run still completes. |
| `JOBHUNTER_HOME` | (M1) app data dir override. |
| *(local, no env var)* Ollama endpoint | Assumed at its default local address (`http://localhost:11434`); not user-configurable in v1 (matches Constitution I's "always local"). |

### Example output (shape, not exact wording)

```
Scoring run <run-id> complete.
  filtered_out: 6   scored: 14   alerted: 2   reranked: 0
```

With `--rerank`:

```
Scoring run <run-id> complete.
  filtered_out: 6   scored: 14   alerted: 2   reranked: 14
```

## Cross-cutting

- Errors are actionable and printed to stderr; the run summary goes to stdout.
- The command writes only into the existing single `jobs.db` (single source of
  truth) plus one outbound ntfy push per alert.
- The web triage board and any tracking states beyond
  new/filtered_out/scored are out of scope here — later milestones.
