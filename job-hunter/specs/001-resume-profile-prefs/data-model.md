# Phase 1 Data Model: Resume Profile & Preferences Foundation

Three persisted artifacts: **Profile** (`profile.json`), **Preferences** (`prefs.yaml`), and the **Job Record** store (`jobs.db`). Field-level JSON Schema for Profile and Preferences lives in [contracts/](./contracts/).

## Entity: Profile

The structured candidate derived once from the resume PDF. One per installation; a new resume submission fully replaces it (FR-004).

| Field | Type | Notes |
|---|---|---|
| `full_name` | string \| null | Best-effort from resume; null if not present. |
| `skills` | string[] | Deduplicated, normalized skill list. Required, non-empty. |
| `experience` | Experience[] | Chronological work history (see below). |
| `seniority` | enum: `junior`\|`mid`\|`senior`\|`staff`\|`principal` \| null | Inferred; null when the resume gives no basis, surfaced as unknown rather than guessed arbitrarily. |
| `roles` | string[] | Past role/title strings (e.g., "Backend Engineer", "Tech Lead"). |
| `total_years_experience` | number \| null | Best-effort computed/estimated. |
| `source_resume_filename` | string | Original filename the profile was derived from. |
| `parsed_at` | ISO-8601 datetime | When the profile was generated. |

### Sub-entity: Experience

| Field | Type | Notes |
|---|---|---|
| `company` | string | |
| `title` | string | |
| `start` | string \| null | Free-form or ISO year/month as found. |
| `end` | string \| null | Null/"present" for current role. |
| `summary` | string \| null | Short description of scope/impact if extractable. |

**Validation rules**:
- `skills` MUST be non-empty for a profile to be considered valid; an all-empty extraction is treated as a parse failure (FR-012), not a valid profile.
- Unknown/unstated fields are `null`, never fabricated (Constitution V — honest representation).
- Persisted atomically: a failed parse leaves any existing `profile.json` untouched.

## Entity: Preferences (`prefs.yaml`)

User-owned matching configuration. Seeded once by the guided interview, hand-editable thereafter (FR-007). Shape mirrors HLD §6.

```yaml
hard_filters:
  locations: [Bangalore, Remote]
  work_modes: [remote, hybrid, onsite]      # subset of the three
  company_types_allow: [product, gcc]
  company_types_deny:  [services, consultancy, staffing]
  comp_floor_lpa: 60
  seniority_floor: senior                    # junior|mid|senior|staff|principal

soft_weights:                                # desirability tuning, sum ~1.0 (guidance)
  work_life_balance: 0.40
  stability:         0.30
  scope:             0.20
  comp:              0.10

alerting:
  score_threshold: 0.70
  max_alerts_per_run: 10
```

**Validation rules** (enforced on every load — FR-013):

| Field | Rule | On violation |
|---|---|---|
| `hard_filters.locations` | non-empty list of strings | error, name field |
| `hard_filters.work_modes` | subset of `{remote, hybrid, onsite}` | error, name offending value |
| `hard_filters.company_types_allow/deny` | strings; allow/deny lists SHOULD NOT overlap | error on overlap |
| `hard_filters.comp_floor_lpa` | number ≥ 0 | error on negative |
| `hard_filters.seniority_floor` | one of the seniority enum | error, name offending value |
| `soft_weights.*` | each a number in [0, 1] | error out of range |
| `soft_weights` sum | ~1.0 (within tolerance, e.g. ±0.05) | **warning only**, value preserved |
| `alerting.score_threshold` | number in [0, 1] | error out of range |
| `alerting.max_alerts_per_run` | integer ≥ 0 | error if negative/non-int |

- Manual edits are honored without re-running the interview (FR-007, FR-008).
- Note: `alerting.*` is defined here for the complete prefs contract but is not consumed until the notifier milestone (M4).

## Entity: Job Record (`jobs` table — schema only in M1)

The durable unit later milestones populate. M1 creates the table empty; it defines the shape so M2–M5 write without redefining it. Mirrors HLD §6.

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PRIMARY KEY | Dedup/idempotency key: source id when stable, else `title\|company\|city` (Constitution IV). |
| `source` | TEXT | `jsearch` \| `adzuna` \| `ats` (populated by M2). |
| `title` | TEXT | |
| `company` | TEXT | |
| `location` | TEXT | |
| `city` | TEXT | |
| `country` | TEXT | |
| `work_mode` | TEXT | `remote` \| `hybrid` \| `onsite`. |
| `description` | TEXT | |
| `employment_type` | TEXT | |
| `salary` | TEXT | Raw/normalized salary string. |
| `apply_url` | TEXT | |
| `score` | REAL | Composite score (M3). Nullable until scored. |
| `breakdown` | TEXT (JSON) | Per-component score breakdown (Constitution V). Nullable. |
| `matched_skills` | TEXT (JSON) | Skills matched vs profile (Constitution V). Nullable. |
| `reason` | TEXT | Re-rank one-line reason (Constitution V). Nullable. |
| `state` | TEXT NOT NULL DEFAULT `'new'` | `new`\|`interested`\|`skipped`\|`applied`\|`interviewing`\|`rejected`. |
| `first_seen` | TEXT (ISO-8601) NOT NULL | Set on first insert (Constitution IV). |
| `last_seen` | TEXT (ISO-8601) NOT NULL | Updated on every rerun that re-sees the job. |
| `updated_at` | TEXT (ISO-8601) NOT NULL | Set on any mutation. |

**Schema/versioning rules**:
- `PRAGMA user_version` stores the schema version to support future migrations.
- `CREATE TABLE IF NOT EXISTS` makes `db init` idempotent — an existing store and its contents are reused, never wiped (FR-011, US3 scenarios 1–2).
- **State transitions** (relevant to later milestones, encoded now): `new → interested`, `new → skipped`, `interested → applied`, `applied → interviewing`, `interviewing → rejected` (and terminal `rejected`/`skipped`). M1 only guarantees the column exists with default `new`; enforcing transitions is M5's concern.

## Relationships

- **Profile ↔ Job Record**: later milestones (M3) compute `matched_skills`/`score` by comparing a Job Record's `description` against the Profile. No FK — Profile is a single JSON artifact, not a table row.
- **Preferences ↔ Job Record**: later milestones (M3) apply `hard_filters` as a gate and `soft_weights` as ranking tuning against Job Records. No storage relationship in M1.
