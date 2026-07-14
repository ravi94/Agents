# Phase 1 Data Model: Job Scoring, Filtering & Alerting

M3 extends the existing M1/M2 `jobs` table (`store/db.py`) with one additive
column and is the first milestone to actually populate the `score`/
`breakdown`/`matched_skills`/`reason` columns M1 reserved. It introduces no
new persistent table.

---

## Entity: Job Record (existing `jobs` table — extended here)

| Column | Owner before M3 | Owner in M3 |
|---|---|---|
| `score` | reserved, null | scoring — overall composite score in `[0, 1]` for jobs that pass all hard filters. |
| `breakdown` | reserved, null | scoring — JSON: per-soft-weight-component scores + which are inferred (see `ScoreBreakdown` below). |
| `matched_skills` | reserved, null | scoring — JSON list of profile skills judged to match this job. |
| `reason` | reserved, null | filtering (why a job was filtered out) **or** optional re-rank (qualitative fit reason) — mutually exclusive by `state`, never both. |
| `state` | `new` only | gains two new values this milestone: `filtered_out` (failed a hard filter) and `scored` (passed filters, has a score). A user-set state from a later triage milestone is never overwritten by rescoring (FR-013). |
| `alerted_at` | **new column** | alerting — ISO-8601 timestamp of the one notification ever sent for this job; `NULL` until the first alert. Never reset, never updated to a later timestamp. |

### New column: `alerted_at`

```sql
ALTER TABLE jobs ADD COLUMN alerted_at TEXT
```

Added idempotently by `init_db` (checked via `PRAGMA table_info(jobs)`) and
tied to `SCHEMA_VERSION = 2` (see [research.md](./research.md) §1). `NULL`
means "never alerted"; once set, it is permanent — this is the mechanism
FR-009 relies on to guarantee at most one notification per job ever,
independent of how many times the job is rescored afterward.

### Validation rules (enforced before a scoring write)

- A job MUST be in `state = 'new'` to be eligible for filtering (already-
  processed jobs — `filtered_out`, `scored`, or any later user-set state —
  are left untouched by a rescoring run, FR-013/FR-014).
- A job transitioning to `filtered_out` MUST NOT receive a `score` or
  `breakdown` (FR-002).
- A job transitioning to `scored` MUST have both `score` and `breakdown` set
  together — never one without the other (FR-006's "no bare number").
- `alerted_at` MUST only ever be written once per job (set from `NULL` to a
  timestamp); a job that already has a non-null `alerted_at` MUST be skipped
  by the alert step regardless of its current score (FR-009).

### State transitions (M3 scope)

```
state=new --hard filter fails--> state=filtered_out, reason=<failed filter(s)>
state=new --passes all hard filters--> state=scored, score=<0..1>, breakdown=<...>, matched_skills=<...>

state=scored, alerted_at=NULL, score>=threshold --alert step--> alerted_at=now (notification sent)
state=scored, alerted_at=NULL, score<threshold  --alert step--> alerted_at stays NULL (no notification)
state=scored, alerted_at=<set>                  --alert step--> no-op regardless of current score (FR-007 rerun scenario)

state=scored --optional --rerank, in top ~25 by score--> reason=<qualitative fit reason> (breakdown untouched)
```

`filtered_out` and `scored` are terminal from this milestone's point of view;
transitions beyond them (e.g. a seeker marking a job "interested") belong to
a later triage milestone and this milestone MUST NOT touch a job already in
such a state.

---

## New entity (persisted as JSON inside `breakdown`): `ScoreBreakdown`

Not a new table — this is the shape written into the existing `breakdown`
column (`json.dumps`) and read back for display/audit.

| Field | Type | Notes |
|---|---|---|
| `overall` | `float` | the same value stored in the `score` column (duplicated here for a self-contained breakdown blob). |
| `components` | `dict[str, ComponentScore]` | one entry per `SoftWeights` field (`work_life_balance`, `stability`, `scope`, `comp`). |
| `computed_at` | `str` | ISO-8601 timestamp of this scoring pass. |

### `ComponentScore`

| Field | Type | Notes |
|---|---|---|
| `value` | `float` | this component's score in `[0, 1]`, before weighting. |
| `weight` | `float` | the `prefs.yaml` soft weight applied (copied at scoring time, so the breakdown stays self-explanatory even if prefs change later). |
| `inferred` | `bool` | `True` for proxy signals (`stability`, `work_life_balance` — company-type-derived); `False` for directly computed ones (`scope`, `comp`) — Constitution V's "represented honestly" requirement. |

---

## In-memory pipeline types (not persisted as separate tables)

### `FilterResult`

| Field | Type | Notes |
|---|---|---|
| `passed` | `bool` | whether the job survives all hard filters. |
| `failed_filters` | `list[str]` | names of the hard-filter dimensions that failed (empty if `passed`); written into `reason` when `not passed`. |

Produced by `scoring/filters.py` for every `state='new'` job, before any
scoring work — "filter before score" (Constitution Technology constraint).
A missing data point for a given filter dimension (e.g. no listed salary for
the comp floor) counts as pass-through for that dimension, not a failure
(FR-003).

### `RerankResult`

| Field | Type | Notes |
|---|---|---|
| `job_id` | `str` | which scored job this reason applies to. |
| `reason` | `str` | short qualitative fit reason from the optional LLM re-rank call. |

Produced by `scoring/rerank.py` only when `--rerank` is passed and only for
the top ~25 `scored` jobs by `score` in the current run (FR-011/FR-012); a
provider failure/timeout here MUST NOT affect already-persisted scores.

### `ScoreRunSummary`

Aggregate outcome of one scoring run (logged at run end; returned to the CLI
for the stdout summary — mirrors M2's `RunSummary` shape).

| Field | Type | Notes |
|---|---|---|
| `filtered_out` | `int` | jobs that failed a hard filter this run. |
| `scored` | `int` | jobs that received a score this run. |
| `alerted` | `int` | notifications actually sent this run. |
| `reranked` | `int` | jobs annotated by the optional LLM pass (`0` if `--rerank` not passed). |
| `run_id` | `str` | correlation id (from `obs`, reused as in M2). |
| `top_job_title` | `str \| None` | title of this run's highest-`overall`-scoring job; `None` if nothing was scored (SC-004). |
| `top_breakdown` | `ScoreBreakdown \| None` | that job's breakdown, so the CLI can render its top contributing factor (`format_breakdown`) without a separate query; `None` if nothing was scored. |

---

## Relationships

```
Preferences (hard_filters, soft_weights, alerting) ─┐
                                                      │
Profile (skills, roles) ───────────────────┐         │
                                            │         │
                          jobs WHERE state='new'      │
                                            │         │
                                            ▼         │
                                 scoring/filters.py ◄──┘
                                     │           │
                              passes │           │ fails
                                     ▼           ▼
                          scoring/scorer.py   state=filtered_out, reason=<why>
                          (+ local Ollama          │
                           embeddings, NumPy)       │
                                     │              │
                                     ▼              │
                    state=scored, score, breakdown, │
                    matched_skills                  │
                                     │              │
                     ┌───────────────┴───────┐      │
                     ▼ (optional --rerank)    ▼      │
           scoring/rerank.py (top ~25)   scoring/alert.py
           reason=<qualitative>          alerted_at (once, if score>=threshold)
                     │                        │
                     └──────────► jobs table ◄┘
                                       │
                              ScoreRunSummary ─► log + stdout + ntfy-on-alert/failure
```

`Preferences` and `Profile` are read-only inputs, exactly as in M2. The
`jobs` table remains the sole persistent output — no new store is introduced.
