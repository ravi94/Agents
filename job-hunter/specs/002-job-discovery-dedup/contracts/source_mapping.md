# Mapping Contract: Source Payload → Canonical `Job`

How each source's raw posting maps to the canonical `Job` columns, and the
work-mode + idempotency-key rules. Implemented in `discovery/normalize.py`,
tested against captured fixtures (`tests/fixtures/jsearch_response.json`,
`adzuna_response.json`). Field names below reflect the sources' documented
payloads; exact keys are pinned by the fixtures at implementation time.

## JSearch (`source = "jsearch"`)

| Canonical column | Source field | Notes |
|---|---|---|
| `title` | `job_title` | required for a usable id. |
| `company` | `employer_name` | required for a usable id. |
| `location` | `job_location` / composed from city+country | raw display location. |
| `city` | `job_city` | may be empty. |
| `country` | `job_country` | may be empty. |
| `work_mode` | `job_is_remote` → see rules | explicit remote flag available. |
| `description` | `job_description` | optional. |
| `employment_type` | `job_employment_type` | optional (e.g. FULLTIME). |
| `salary` | `job_min_salary`/`job_max_salary`/period | optional; rendered to a readable string, else null (never fabricated). |
| `apply_url` | `job_apply_link` | optional. |
| `id` | see idempotency rule | JSearch `job_id` is aggregate-derived → treat as **not stable**; use fallback composite. |

## Adzuna India (`source = "adzuna"`)

| Canonical column | Source field | Notes |
|---|---|---|
| `title` | `title` | required. |
| `company` | `company.display_name` | required. |
| `location` | `location.display_name` | raw display location. |
| `city` | `location.area[…]` best-effort | parse from the area hierarchy; may be empty. |
| `country` | `location.area[0]` (country) | may be empty. |
| `work_mode` | text-inferred → see rules | no explicit remote flag. |
| `description` | `description` | optional. |
| `employment_type` | `contract_time`/`contract_type` | optional. |
| `salary` | `salary_min`/`salary_max`/`salary_is_predicted` | optional; predicted salaries rendered honestly or omitted, never invented. |
| `apply_url` | `redirect_url` | optional. |
| `id` | see idempotency rule | Adzuna `id` is reasonably stable per posting → MAY be used as the source id. |

## Work-mode classification rules (both sources)

Applied in order; first match wins (FR-009):

1. Explicit remote flag true (JSearch `job_is_remote == true`) → `remote`.
2. Text (title + description), case-insensitive keyword scan:
   - `remote`, `work from home`, `wfh`, `fully remote` → `remote`
   - `hybrid` → `hybrid`
   - `onsite`, `on-site`, `in office`, `in-office` → `onsite`
3. No signal → `unknown` (MUST NOT be guessed as a specific mode).

## Idempotency-key rules (`id`)

Computed for **every** posting (FR-012, Constitution IV):

1. If the source id is stable (Adzuna `id`) → `id = "<source>:<source_id>"`.
2. Else (JSearch) → normalized composite: lowercase, trim, collapse internal
   whitespace of `title`, `company`, `city`, joined `title|company|city`.
   - Missing `city` → composite uses `title|company` (still deterministic).
3. If `title` AND `company` are both absent → **no usable id**: the posting is
   skipped and counted in `RunSummary.skipped` (FR-011), never stored.

### Cross-source dedup

The same role on both JSearch and Adzuna typically has different source ids, so
it collapses through the **composite** path (rule 2), not the source id. Because
Adzuna prefers its stable source id (rule 1) while JSearch always uses the
composite, cross-source duplicates are matched only when both resolve to the same
composite — so the normalizer additionally records the composite for stable-id
postings to enable within-run cross-source collapse. Within a single run,
postings sharing a resolved key are collapsed to one record, preferring the
richer payload (more non-null optional fields) deterministically.

## Optional-field discipline

Any source field absent from a payload maps to `None`/empty in the canonical
record — the normalizer MUST NOT substitute defaults or infer values for
`salary`, `employment_type`, `description`, or `apply_url` (FR-010,
Constitution V spirit: no fabricated signal).
