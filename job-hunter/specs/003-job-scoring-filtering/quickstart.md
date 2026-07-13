# Quickstart: Validating Job Scoring, Filtering & Alerting (M3)

Proves the M3 pipeline end-to-end: hard filters gate scoring, scored jobs
carry an inspectable breakdown, alerts fire once and never repeat, and the
optional re-rank stays bounded. See [contracts/cli.md](./contracts/cli.md) and
[data-model.md](./data-model.md) for the full behavioral contract.

## Prerequisites

- M1 complete: `profile.json` and `prefs.yaml` exist (`jobhunter profile`,
  `jobhunter prefs init`).
- M2 complete: `jobhunter discover` has populated `jobs.db` with `state='new'`
  rows (or seed the store directly with fixture rows for a fully offline run).
- (Optional, only for the embeddings-backed `scope` component) Ollama running
  locally with `mxbai-embed-large` pulled: `ollama pull mxbai-embed-large`.
  Without it, `scope` falls back to keyword overlap — the run still completes.
- (Optional, only for `--rerank`) Claude CLI logged in, same as `jobhunter
  profile`'s prerequisite.

```bash
export JOBHUNTER_HOME="$(pwd)/data"   # keep state inside the repo
```

## Scenario 1 — Filter and score (US1)

```bash
.venv/bin/jobhunter score --dry-run
```

**Expected**: A summary line `filtered_out: N   scored: M   alerted: 0
reranked: 0`; nothing written (dry run). Re-run without `--dry-run`:

```bash
.venv/bin/jobhunter score
```

**Expected**: Jobs that failed a hard filter now have `state=filtered_out`
and a `reason` naming the failed dimension(s); jobs that passed have
`state=scored` with a non-null `score` and `breakdown`. Verify with:

```bash
.venv/bin/python -c "
from jobhunter import config
from jobhunter.store import db
import sqlite3
conn = sqlite3.connect(config.db_path()); conn.row_factory = sqlite3.Row
for row in conn.execute('SELECT id, state, score, reason FROM jobs LIMIT 5'):
    print(dict(row))
"
```

## Scenario 2 — Explainable breakdown (US2)

For any `state='scored'` job, confirm the persisted `breakdown` JSON contains
a per-component score (`work_life_balance`, `stability`, `scope`, `comp`) and
that `matched_skills` is a non-null list (possibly empty). Confirm
`stability`/`work_life_balance` are marked `inferred: true` in the breakdown,
while `scope`/`comp` are not.

## Scenario 3 — Alert once, never twice (US3)

```bash
export JOBHUNTER_NTFY_TOPIC="my-test-topic"   # or watch stdout/log if unset
.venv/bin/jobhunter score       # first run over new jobs — some may alert
.venv/bin/jobhunter score       # second run — no new `new` jobs to process
```

**Expected**: The second run reports `alerted: 0` (nothing left in `state=new`
to alert on); no job that was alerted in the first run receives a second
notification even if its score were to be recomputed by a future rescoring
path. Confirm each alerted job's `alerted_at` is non-null and unchanged
across runs.

## Scenario 4 — Optional re-rank stays bounded (US4)

```bash
.venv/bin/jobhunter score --rerank
```

**Expected**: `reranked` in the summary is `min(scored_this_run, 25)`; exactly
one LLM call is made regardless of how many jobs were scored (verify via the
run log — one `start scoring.rerank` / `ok scoring.rerank` trace pair).
Disable and confirm the rest of the pipeline is unaffected:

```bash
.venv/bin/jobhunter score   # no --rerank
```

**Expected**: Filtering, scoring, and alerting behave identically to Scenario
1/3; `reranked: 0`.

## Cleanup

```bash
unset JOBHUNTER_NTFY_TOPIC
```

`data/` stays gitignored (per M1); no cleanup of `jobs.db` is needed between
runs — the pipeline is idempotent by design (Constitution IV).
