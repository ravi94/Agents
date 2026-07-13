# Phase 1 Data Model: Job Discovery, Normalization & Dedup

M2 introduces **no new persistent store** — it writes into the existing M1
`jobs` table (`store/db.py`). This document describes the canonical `Job` view
used during discovery, the in-memory pipeline types, the additive optional
preferences field, and the one store seam this milestone adds.

---

## Entity: Job Record (existing `jobs` table — populated here)

Defined in M1 [data-model](../001-resume-profile-prefs/data-model.md) and created
by `store/db.py`. M2 is the first writer of real rows. Column ownership in M2:

| Column | Owner in M2 | Notes |
|---|---|---|
| `id` | discovery (dedup key) | source job id when stable, else `title\|company\|city` composite (normalized). Constitution IV. |
| `source` | discovery | `jsearch` / `adzuna` (later `ats`). |
| `title`, `company`, `location`, `city`, `country` | normalizer | `location` = raw source location text; `city`/`country` parsed best-effort (may be empty). |
| `work_mode` | normalizer | one of `remote` / `hybrid` / `onsite` / `unknown` (FR-009). |
| `description`, `employment_type`, `salary`, `apply_url` | normalizer | optional fields left empty/null when absent — never fabricated (FR-010). |
| `score`, `breakdown`, `matched_skills`, `reason` | **not set** | remain null; M3 (scoring) populates them. |
| `state` | store default | `new` on first insert; **never reset** on re-sighting (FR-015). |
| `first_seen` | store | stamped once on first insert; preserved across runs. |
| `last_seen` | store | advanced every time the job is seen again (`touch_last_seen`). |
| `updated_at` | store | set on insert/content-update; **not** bumped by a pure re-sighting. |

### Validation rules (enforced before insert)

- `id` MUST be non-empty (store raises otherwise). A posting yielding no id
  (missing title AND company AND city) is **skipped and counted**, not stored (FR-011).
- `work_mode` MUST be one of the four allowed values.
- `source` MUST be a known source name.
- Optional fields absent in the payload MUST be `None`/empty, never guessed.

### State transitions (M2 scope)

```
(absent) --discover, never seen--> state=new, first_seen=now, last_seen=now
state=X  --discover, already seen--> state=X (unchanged), last_seen=now
```

M2 only ever creates `new` or advances `last_seen`. It never transitions
between triage/tracking states — those are user actions in later milestones — and
MUST NOT reset a non-`new` state back to `new`.

---

## In-memory pipeline types (not persisted)

### `SearchQuery`
The derived instruction for one source lookup.

| Field | Type | Notes |
|---|---|---|
| `keywords` | `str` | one role/title term (e.g. "Staff Backend Engineer"). |
| `location` | `str` | one preference location (e.g. "Bangalore", "Remote"). |

Derivation (`discovery/query.py`): default = `profile.roles` (or a coarse term
from `profile.seniority` if roles empty) × `prefs.hard_filters.locations`, capped
by the per-source query budget. `prefs.search.keywords`, when present, replaces
the profile-derived keyword set. Empty on both sides → no queries → clean no-op.

### `RawPosting`
A source-shaped posting dict as returned by a `JobSource`, before normalization.
Opaque to the orchestrator; only the per-source normalizer interprets it.

### `NormalizedJob`
A dict matching the settable `Job` columns (`source`, `title`, …, `work_mode`,
…, `apply_url`) plus the computed `id`. This is what dedup and the store consume.
Store-managed columns (`first_seen`/`last_seen`/`updated_at`/`state`) are NOT
included — the store owns them.

### `RunSummary`
Aggregate outcome of one discovery run (logged at run end; returned to the CLI
for the stdout summary).

| Field | Type | Notes |
|---|---|---|
| `fetched` | `int` | total raw postings across sources. |
| `new` | `int` | genuinely new jobs inserted (state `new`). |
| `seen` | `int` | already-known jobs whose `last_seen` was advanced. |
| `skipped` | `int` | postings dropped as unnormalizable (FR-011). |
| `source_failures` | `dict[str, str]` | source name → failure reason (metadata only). |
| `run_id` | `str` | correlation id (from `obs`). |

---

## Additive model change: optional `search` in Preferences

`models/preferences.py` gains an **optional** block (existing M1 `prefs.yaml`
files remain valid — the field defaults to absent):

```python
class SearchPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keywords: list[str] = Field(default_factory=list)   # override for discovery terms

class Preferences(BaseModel):
    hard_filters: HardFilters
    soft_weights: SoftWeights
    alerting: Alerting
    search: SearchPrefs | None = None   # NEW — optional; None = derive from profile
```

- When `search` is absent or `search.keywords` is empty → derive keywords from
  the profile (FR-003 default path).
- When `search.keywords` is non-empty → it replaces the profile-derived keywords
  (locations from `hard_filters.locations` still apply).
- `extra="forbid"` is preserved; adding the optional field does not reject old files.

---

## Store seam added: `touch_last_seen`

New function in `store/db.py` (see [research.md](./research.md) §7):

```
touch_last_seen(id: str, path: Path | None = None) -> bool
```

- Advances `last_seen` to now for the row with `id`; returns `True` if a row was
  updated, `False` if `id` is absent.
- Leaves `first_seen`, `state`, `updated_at`, and all content columns untouched.
- Used by the dedup/persist step for the **already-seen** path; the **new** path
  reuses the existing `upsert_job` unchanged.

---

## Relationships

```
Profile (M1) ─┐
              ├─► SearchQuery ─► JobSource.fetch ─► RawPosting
Preferences ──┘                                        │
 (locations, optional search)                          ▼
                                              normalize + classify work_mode
                                                       │
                                                  NormalizedJob (id)
                                                       │
                                             dedup (within-run + vs store)
                                              │                    │
                                          new │                    │ seen
                                              ▼                    ▼
                                     store.upsert_job      store.touch_last_seen
                                              │                    │
                                              └──────► jobs table ◄┘
                                                       │
                                                  RunSummary ─► log + stdout + ntfy-on-fail
```

`Profile` and `Preferences` are read-only inputs here. The `jobs` table is the
sole persistent output. No LLM, embedding, or scoring entity participates in M2.
