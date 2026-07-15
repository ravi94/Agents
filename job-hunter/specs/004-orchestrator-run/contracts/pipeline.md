# Composition Contract: `run_pipeline`

The one new production seam this milestone adds. Lives in
`src/jobhunter/pipeline/run.py`. It composes the two existing stage runners; it
owns no store writes, no LLM call, and no ntfy call of its own.

## Signature

```python
def run_pipeline(
    sources: list[JobSource],
    profile: Profile,
    prefs: Preferences,
    *,
    dry_run: bool = False,
    rerank: bool = False,
    provider: LLMProvider | None = None,
) -> PipelineSummary:
    ...
```

- `sources` — the discovery sources to attempt (built by the CLI from `--source`,
  default all configured). Passed straight to `run_discovery`.
- `profile`, `prefs` — loaded by the CLI; passed to both stages.
- `dry_run` — propagated to **both** `run_discovery` and `run_scoring`.
- `rerank`, `provider` — passed to `run_scoring`. As in M3, `provider` is only
  constructed by the CLI when `--rerank` is set; when `rerank` is `False`,
  `provider` is untouched (`reranked == 0`).

Returns a `PipelineSummary(run_id, discovery, scoring)` — see
[data-model.md](../data-model.md).

## Behavioral contract

| # | Rule |
|---|---|
| C1 | Calls `run_discovery(sources, profile, prefs, dry_run=dry_run)` first, then `run_scoring(profile, prefs, dry_run=dry_run, rerank=rerank, provider=provider)` — always in that order (filter-before-score at the pipeline level). |
| C2 | Does **not** mint a run id. Reads `obs.current_run_id()` (configured once by `cli.main()`) for `PipelineSummary.run_id`; both stages already reuse the same id, so all log lines and both summaries agree. |
| C3 | Does **not** loop over sources or wrap `run_discovery` in a try/except that would defeat its internal per-source isolation. A single source failure is reported inside `discovery.source_failures`, never raised. |
| C4 | Calls `run_scoring` **unconditionally** after discovery — even if discovery added zero new jobs or every source failed — so pre-existing `state='new'` jobs are still scored. |
| C5 | Builds `PipelineSummary` from the two returned summaries without recomputing or copying their inner fields. |
| C6 | Emits one end-of-run summary log line (via `obs.get_logger`) covering both stages' headline counts, in addition to the per-stage lines the stages already log. |
| C7 | Raises on an aborting error (e.g. propagated store-unwritable). It does **not** call `obs.notify_error` itself — `cli.main()` owns the whole-run failure ntfy. Per-role alerts remain `run_scoring`'s responsibility. |
| C8 | With `dry_run=True`, performs zero store writes and zero notification sends across both stages, while both nested summaries still report the would-be counts. |

## What it explicitly does NOT do

- No new schema/column/store (C5 aggregates existing summaries only).
- No new LLM touchpoint (the only text-generation call is M3's optional rerank,
  reached through the unchanged `provider` seam).
- No scheduler, no retry loop, no new source (composition only).
- No new correlation id, no new ntfy channel (reuses `obs`).

## Test contract (TDD — write first, observe fail)

| Test | Asserts |
|---|---|
| order | `run_discovery` is invoked before `run_scoring` (e.g. recorded call order with stage runners stubbed). |
| isolation propagation | Given a discovery summary carrying a `source_failures` entry, `run_scoring` is still invoked and the run returns normally (C3, C4). |
| scoring-runs-when-empty | With discovery returning zero new jobs, `run_scoring` is still called (C4). |
| flag pass-through | `dry_run` reaches both stages; `rerank`/`provider` reach `run_scoring`; `sources` reach `run_discovery` (C1, C8). |
| summary aggregation | `PipelineSummary` exposes both stages' counts and the shared `run_id` without mutation (C2, C5). |
| run-id reuse | `PipelineSummary.run_id == obs.current_run_id()`, and equals both nested summaries' `run_id` (C2). |
| integration (mocked network/LLM) | Real `run_pipeline` over fixture sources + fixture store: new jobs discovered then scored; above-threshold new job alerts once; `--dry-run` leaves the store unchanged and sends nothing. |

No test may depend on a live JSearch/Adzuna/Ollama/Claude call (Constitution VII).
