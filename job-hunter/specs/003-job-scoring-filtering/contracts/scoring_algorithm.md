# Contract: Composite Scoring Algorithm

Defines the deterministic contract that `scoring/filters.py` and
`scoring/scorer.py` must satisfy, independent of implementation. See
[data-model.md](../data-model.md) for the persisted shapes and
[research.md](../research.md) §2 for the design rationale.

## Hard filters (gate before any scoring)

Applied in this order; a job fails on the **first** dimension it violates,
but `failed_filters` collects **every** dimension it violates (not just the
first) so `reason` is complete:

| Filter | Pass condition | Missing-data behavior |
|---|---|---|
| `locations` | Job's `city`/`location` matches one of `hard_filters.locations` (case-insensitive), or job `work_mode == "remote"`. | N/A — location is always present from M2 normalization. |
| `work_modes` | Job's `work_mode` is one of `hard_filters.work_modes`, or job `work_mode == "unknown"`. | `unknown` work_mode passes through (treated as "could not determine", not a violator) per FR-003. |
| `company_types` | If `company_types_deny` is non-empty and the job's company type matches one → fail. If `company_types_allow` is non-empty and the job's company type does not match any → fail. | A job with no determinable company type passes through both checks. |
| `comp_floor_lpa` | Job's parsed salary (annualized, LPA) >= `comp_floor_lpa`. | No listed salary → pass-through (FR-003); comp floor is enforced only when a number exists to compare. |
| `seniority_floor` | Job's inferred seniority >= `hard_filters.seniority_floor` on the fixed order `junior < mid < senior < staff < principal`. | Undeterminable seniority → pass-through. |

A job passing every filter proceeds to scoring; a job failing one or more is
written as `state=filtered_out`, `reason="failed: <comma-joined dimensions>"`.

## Composite score

```
overall = Σ (component[name].value * soft_weights[name])   for name in
          {work_life_balance, stability, scope, comp}
```

- `overall` is **not** re-normalized by the sum of the weights — weights are
  used exactly as configured in `prefs.yaml` (consistent with M1's existing
  "sum drift is a warning, not a rewrite" policy). A weight sum below 1.0
  therefore caps the achievable `overall`; this is expected and intentional,
  not a bug to compensate for silently.
- Each `component[name].value` is independently in `[0, 1]`; `overall` is
  therefore in `[0, weight_sum]`, typically `[0, ~1]`.

### Component definitions

| Component | Computation | `inferred` |
|---|---|---|
| `comp` | `min(job_salary / hard_filters.comp_floor_lpa, 1.0)` when salary is present; `0.5` (neutral) when absent. | `False` |
| `scope` | Cosine similarity between the local-Ollama (`mxbai-embed-large`) embedding of `job.title + job.description` and the embedding of `profile.skills + profile.roles`, rescaled from `[-1, 1]` to `[0, 1]`. Falls back to keyword-overlap ratio if the local embedding endpoint is unavailable (traced/logged). | `False` |
| `stability` | Lookup against a fixed company-type → stability-signal table (e.g. large/public-company proxies score higher than early-stage-startup proxies); `0.5` when company type is undeterminable. | `True` |
| `work_life_balance` | Lookup against the same company-type signal, a separate fixed table; `0.5` when undeterminable. | `True` |

## `matched_skills`

Populated alongside `scope`: every profile skill whose individual embedding
scores above a fixed similarity threshold against the job text, ordered by
similarity descending. Empty list (not null) when no skill clears the
threshold — an empty match is itself informative and distinct from "not yet
computed".

## Determinism & idempotency

- Given the same job row, profile, and prefs, scoring MUST produce the same
  `overall`/`breakdown`/`matched_skills` on repeated runs (embeddings are a
  pure function of text; no randomness, no model sampling temperature
  involved for this component).
- Rescoring a job already in `state='scored'` or `state='filtered_out'` MUST
  NOT happen — scoring only ever processes `state='new'` jobs (see
  [data-model.md](../data-model.md) state transitions).

## Explainability constraint (Constitution V)

- `score` MUST NOT be written without an accompanying `breakdown` — enforced
  at the store layer by writing both in the same transaction.
- Any `inferred: true` component MUST remain labeled as such wherever the
  breakdown is displayed — never presented as a directly observed fact.
