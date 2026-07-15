# Phase 1 Data Model: End-to-End Pipeline Orchestrator

This milestone introduces **no persisted data and no schema change**. The store
stays at schema version 2 (M3). The only new entity is one in-memory aggregate
that composes the two existing stage summaries for one run.

## PipelineSummary (in-memory only)

The aggregate outcome of one orchestrated `jobhunter run`. Not persisted — built,
logged (end-of-run summary), printed, and discarded.

| Field | Type | Notes |
|---|---|---|
| `run_id` | `str` | The shared process correlation id (`obs.current_run_id()`). Identical to both nested summaries' `run_id`. `"-"` only outside a configured run (library/test use). |
| `discovery` | `RunSummary` | The M2 discovery stage's existing summary — see below. |
| `scoring` | `ScoreRunSummary` | The M3 scoring/alerting stage's existing summary — see below. |

**Composition rule**: `run_pipeline` constructs `PipelineSummary` from the two
values it gets back from `run_discovery` and `run_scoring`; it never recomputes or
copies their inner fields. If a stage is skipped (it never is in the normal path —
both always run), its slot would hold that stage's zero-value summary rather than
`None`, so rendering is always total.

### Convenience accessors (optional, if rendering needs them)

Rendering may expose read-through helpers (e.g. `discovered`, `new`, `deduped`,
`filtered_out`, `scored`, `alerted`) that simply read the nested summaries. These
are presentation conveniences, not stored state.

## Reused entity: RunSummary (M2 — unchanged)

From `discovery/run.py`. Consumed as-is; **not modified** by this milestone.

| Field | Type | Meaning for the combined summary |
|---|---|---|
| `fetched` | `int` | total roles fetched across sources (discovered) |
| `new` | `int` | genuinely new roles persisted |
| `seen` | `int` | already-seen roles (deduped, `last_seen` touched) |
| `skipped` | `int` | roles skipped (e.g. unusable) |
| `source_failures` | `dict[str, str]` | source name → failure reason (per-source isolation, FR-004) |
| `attempted_sources` | `list[str]` | sources attempted this run |
| `run_id` | `str` | same shared run id |

> Mapping to the spec's "per-source discovered/new/deduplicated counts": `fetched`
> = discovered, `new` = new, `seen` = deduplicated (already-known) — reported per
> the existing summary's granularity plus the per-source ok/failed breakdown from
> `attempted_sources` + `source_failures`.

## Reused entity: ScoreRunSummary (M3 — unchanged)

From `scoring/run.py`. Consumed as-is; **not modified** by this milestone.

| Field | Type | Meaning for the combined summary |
|---|---|---|
| `filtered_out` | `int` | roles rejected by a hard filter |
| `scored` | `int` | roles scored with a persisted breakdown |
| `alerted` | `int` | new above-threshold roles that fired exactly one ntfy alert |
| `reranked` | `int` | roles given a qualitative reason via the optional `--rerank` pass (0 unless `--rerank`) |
| `run_id` | `str` | same shared run id |
| `top_job_title` | `str \| None` | this run's highest-scoring role (for the summary line) |
| `top_breakdown` | `ScoreBreakdown \| None` | its breakdown, so the top contributor is legible without a query |

## Reused entity: Job (M1–M3 — unchanged)

The stored role record. The orchestrator does not add or change any field; it only
causes the job to advance through the existing states within one run:

```
(discovery)  → new
(scoring)    → filtered_out  (hard-filter reject, with reason)
             → scored        (with score + breakdown + matched_skills [+ reason if reranked])
(alerting)   → alerted_at stamped once, iff new & score ≥ threshold
```

No new state, no new column, no migration.

## State & invariants introduced by the orchestrator

The orchestrator adds **no new persistent state**. It must preserve these
inherited invariants when composing the stages (each is asserted by a test):

- **I1 — Ordering**: discovery completes before scoring begins (filter-before-score
  holds at the pipeline level, not just within scoring).
- **I2 — Isolation**: a single source failure appears in
  `discovery.source_failures` and does **not** prevent `scoring` from running.
- **I3 — Write-once alert**: across repeated runs, an above-threshold role's
  `alerted` contribution totals exactly one (inherited `alerted_at` write-once).
- **I4 — Rehearsal purity**: with `--dry-run`, neither nested stage writes to the
  store or sends any notification, yet both summaries still report the counts the
  run would have produced.
