# Quickstart: End-to-End Pipeline Orchestrator (M4)

Validates that `jobhunter run` executes the whole pipeline end to end in one
command, isolates a dead source, reports one combined summary under one run id,
and rehearses safely with `--dry-run`. Proves SC-001…SC-007.

Live JSearch/Adzuna/Ollama/Claude are **optional** — the automated suite mocks
all network/LLM. A real end-to-end run is a manual confidence check, not a test
pass condition (Constitution VII).

## Prerequisites

- Python 3.11+ project venv installed (`uv sync` / existing `.venv`).
- A persisted profile (`jobhunter profile <resume.pdf>`) and valid prefs
  (`jobhunter prefs validate`), same preconditions as `discover`/`score`.
- Store present or auto-created (`jobhunter db init`).
- Optional for a real run: source API keys in `.env`, a local Ollama instance,
  and `JOBHUNTER_NTFY_TOPIC` set to see alerts/error signals.

## Automated validation (no live calls)

Run the M4 suite (unit + integration, network/LLM mocked):

```bash
.venv/bin/pytest tests/unit/test_pipeline_run.py \
                 tests/unit/test_cli_run.py \
                 tests/integration/test_run_end_to_end.py -q
```

Expected: green. These assert the composition contract in
[contracts/pipeline.md](./contracts/pipeline.md) — order, failure isolation,
flag pass-through, summary aggregation, run-id reuse, and the mocked
end-to-end path.

## Manual end-to-end scenarios

### Scenario 1 — one command runs the whole pipeline (SC-001, US1)

```bash
jobhunter run
```

Expect: a single combined summary printed — a discovery block (per-source
ok/failed + fetched/new/seen/skipped) followed by a scoring block
(filtered_out/scored/alerted/reranked + top contributor), all under one
`run-id`. Newly-discovered jobs end up filtered-out or scored in the store,
exactly as running `discover` then `score` would have. Exit code `0`.

### Scenario 2 — one dead source never kills the run (SC-002, US2)

Force one source to fail (e.g. invalidate one source's key, or select a source
whose endpoint is down) and run again:

```bash
jobhunter run --source jsearch --source adzuna
```

Expect: the failing source shows `failed <reason>` in the discovery block, the
healthy source's jobs still flow through to scoring, and the command still exits
`0`. Confirm scoring ran (its block is present with non-error counts).

### Scenario 3 — one run id, one summary, error on failure (SC-003, SC-004, SC-006, US3)

```bash
jobhunter run
grep "<run-id-from-output>" ~/.job-hunter/logs/jobhunter.log | head
```

Expect: every log line for that run carries the same `run-id`; each source call
and any re-rank call is traced with outcome/duration and **no** personal payload;
the end-of-run summary line reports both stages' counts. Then force a whole-run
failure (e.g. make the store unwritable) and confirm an ntfy error signal fires
and the command exits non-zero.

### Scenario 4 — no double-alert across runs (SC-005)

Run twice over the same store with an above-threshold new role:

```bash
jobhunter run
jobhunter run
```

Expect: exactly one alert total across the two runs (`alerted` is `0` on the
second run for that role); `alerted_at` set once and unchanged.

### Scenario 5 — rehearsal writes nothing (SC-007, US4)

```bash
jobhunter run --dry-run
```

Expect: the combined summary reports the counts the run *would* have produced,
but the store is unchanged (no new jobs, no state transitions, no `alerted_at`
stamps) and no notification is sent. Re-running without `--dry-run` then performs
the real run.

### Scenario 6 — optional qualitative re-rank (US4 of M3, surfaced via `run`)

```bash
jobhunter run --rerank
```

Expect: identical to Scenario 1 plus `reranked > 0` in the scoring block (top ~25
survivors get a `reason`); a provider failure leaves the rest of the run intact
and still exits `0`.

## Success criteria mapping

| Criterion | Scenario |
|---|---|
| SC-001 one command, zero manual steps | 1 |
| SC-002 healthy sources complete despite a failure | 2 |
| SC-003 single correlation id across the run | 3 |
| SC-004 combined summary at a glance | 1, 3 |
| SC-005 exactly one alert across re-runs | 4 |
| SC-006 whole-run failure always notified | 3 |
| SC-007 rehearsal leaves store unchanged, sends nothing | 5 |
