# Feature Specification: Job Discovery, Normalization & Dedup

**Feature Branch**: `002-job-discovery-dedup`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "M2 — Job Discovery, Normalization & Dedup. Fetch job postings from two aggregator sources (JSearch and Adzuna India) behind a common pluggable JobSource interface, normalize each source's payload into the canonical Job shape (including best-effort work-mode classification), and dedup across sources and across runs using a stable idempotency key checked against the existing SQLite store from M1. Genuinely new jobs are inserted with state=new and first_seen set; already-seen jobs update last_seen only and are not re-processed as new. Discovery queries are derived from prefs.yaml/profile. Must honor per-source isolation (one dead source never fails the run), aggregator free-tier rate limits (bounded queries, caching, backoff on 429), and full observability. Scope is discover→normalize→dedup→persist-new only; scoring, filtering, alerting, and the web board are later milestones."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Discover and persist genuinely new jobs (Priority: P1) 🎯 MVP

A job seeker triggers a discovery run. The system queries an external job source using search terms derived from the seeker's profile and location preferences, converts each returned posting into a consistent internal job record (title, company, location breakdown, work mode, description, pay, apply link, and identity), checks each against the existing job store, and saves any job it has never seen before as a brand-new record ready for later scoring and triage. The seeker ends the run with new roles captured durably in the store — no scoring or alerting yet, just reliable capture.

**Why this priority**: Nothing downstream (scoring, triage, tracking) can exist without a populated job store. Turning external postings into persisted, deduplicated canonical records is the single foundational capability of this milestone and delivers standalone value: a growing, inspectable inventory of relevant roles.

**Independent Test**: Run discovery against a single source (with a recorded/fixture response so no live API is required); verify each returned posting becomes a canonical job record with the expected fields populated, that records unseen before are stored with state "new" and a first-seen timestamp, and that the run reports how many jobs were fetched versus newly stored.

**Acceptance Scenarios**:

1. **Given** an empty job store and a source that returns several postings, **When** a discovery run executes, **Then** each posting is stored as a canonical job record with title, company, location/city/country, work mode, description, employment type, salary (when available), apply link, and a stable identity, each with state "new" and a first-seen timestamp.
2. **Given** a source returns a posting missing optional details (e.g., no salary), **When** it is normalized, **Then** the record is still stored with the missing optional fields left empty/unknown rather than fabricated, and required identity fields are still present.
3. **Given** the discovery run completes, **When** it finishes, **Then** it reports a per-run summary including total fetched and total newly stored.

---

### User Story 2 - Re-run without duplicates or re-alerts (monitor semantics) (Priority: P2)

The seeker runs discovery again later. Postings they have already seen must not create duplicate records or be treated as new again; instead the system recognizes them by their stable identity, refreshes a "last seen" marker so it knows the role is still live, and leaves their existing state and first-seen timestamp untouched. Only postings never seen before are added as new. This is what turns a repeated search into a monitor.

**Why this priority**: The copilot's core promise is to remember what it has shown and surface only genuinely new roles. Without cross-run idempotency, every re-run would re-add and (in later milestones) re-alert the same jobs, destroying the signal. This is second only to capturing jobs at all.

**Independent Test**: Run discovery twice over the same source response; verify that after the second run no duplicate records exist, previously stored jobs have an updated last-seen timestamp but an unchanged first-seen timestamp and unchanged state, and only truly new postings are added as new.

**Acceptance Scenarios**:

1. **Given** a job already exists in the store from a prior run, **When** a later run returns that same posting, **Then** no duplicate record is created, the job's last-seen timestamp is updated, and its first-seen timestamp and state are left unchanged.
2. **Given** a posting whose source lacks a stable identifier, **When** it recurs across runs, **Then** it is matched to the existing record using a fallback identity of title + company + city (not re-added).
3. **Given** a run returns a mix of already-seen and never-seen postings, **When** it completes, **Then** only the never-seen postings are stored as new, and the run summary reports new versus already-seen counts.

---

### User Story 3 - Resilient multi-source discovery (Priority: P3)

The seeker wants coverage from more than one source and expects the run to survive a flaky one. The system queries multiple sources through a single common interface, merges their results, deduplicates a role that appears in more than one source into a single record, and — if any one source errors, times out, or is rate-limited — logs and skips that source while still completing the run with results from the healthy sources. New sources can be added later without changing the code that orchestrates a run.

**Why this priority**: Two live aggregators plus future ATS endpoints mean partial failure is normal; a run that dies because one source is down is useless for an unattended monitor. Multi-source coverage and per-source isolation make discovery dependable, but they build on the single-source capture and idempotency already delivered by US1 and US2.

**Independent Test**: Run discovery with two sources where one returns results and the other raises an error; verify the run completes, stores the healthy source's new jobs, records the failed source in the run summary, and exits without failing. Separately, feed the same role from both sources and verify it is stored once.

**Acceptance Scenarios**:

1. **Given** two configured sources where one raises an error or times out, **When** a run executes, **Then** the healthy source's results are still normalized and stored, the failed source is logged and counted as a per-source failure in the run summary, and the run does not abort.
2. **Given** the same role is returned by two different sources in one run, **When** results are deduplicated, **Then** it is stored as a single canonical record rather than two.
3. **Given** a source responds that its rate limit is exceeded, **When** the run encounters this, **Then** it backs off and retries within bounded limits, and if still unavailable, treats the source as a per-source failure rather than failing the whole run.
4. **Given** a new source is introduced later, **When** it implements the common source interface, **Then** it can be included in a run without changing the run orchestration logic.

---

### Edge Cases

- **No usable search terms**: If neither the profile nor preferences yield any search keywords, the run does nothing external, logs the reason, and exits cleanly rather than issuing an unbounded/empty query.
- **Work mode not determinable**: When a source gives no reliable remote/hybrid/onsite signal and it cannot be inferred from text, work mode is recorded as unknown rather than guessed as a specific mode.
- **Malformed/partial source payload**: A single posting that cannot be normalized (missing required identity fields) is skipped and counted, without aborting the rest of the batch.
- **Duplicate within a single run**: The same posting appearing twice in one source's own results is collapsed to one record.
- **Empty result set**: A source that legitimately returns zero postings is a success (zero new), not a failure.
- **Query volume ceiling reached**: When the per-run query budget for a source is exhausted, discovery stops querying that source for the run and records that the budget was reached.
- **Store already contains a job under a different state** (e.g., a later milestone marked it "interested"): a recurring posting must update last-seen only and must never reset that state back to "new".
- **Location present but city not parseable**: The record still stores whatever location text is available; city/country may be empty without failing normalization.

## Requirements *(mandatory)*

### Functional Requirements

**Discovery & sources**

- **FR-001**: System MUST fetch job postings from at least two external aggregator sources (JSearch and Adzuna India) during a discovery run.
- **FR-002**: System MUST expose all sources through a single common source interface so that adding a future source (e.g., an ATS watchlist) requires no change to the run-orchestration logic.
- **FR-003**: System MUST derive discovery search terms from the seeker's persisted profile (target roles and seniority) crossed with the location preferences from `prefs.yaml`, and MUST allow an optional user-provided search override in `prefs.yaml` to take precedence when present.
- **FR-004**: System MUST bound the number of queries/requests issued per source per run to stay within aggregator free-tier limits, and MUST record when a per-run query budget is reached.
- **FR-005**: System MUST cache source responses so that repeated identical queries within a bounded freshness window do not re-hit the external API.
- **FR-006**: System MUST back off and retry within bounded limits when a source signals its rate limit is exceeded (HTTP 429), and MUST treat a source still unavailable after bounded retries as a per-source failure rather than a run failure.
- **FR-007**: System MUST NOT scrape LinkedIn or any source in violation of its terms; only sanctioned aggregator/source endpoints are used.

**Normalization**

- **FR-008**: System MUST convert each source-specific posting into a single canonical job record containing: identity, source, title, company, location, city, country, work mode, description, employment type, salary, and apply link.
- **FR-009**: System MUST classify each job's work mode as remote, hybrid, onsite, or unknown, using a source's explicit remote signal when available and a best-effort text inference otherwise, and MUST record "unknown" rather than guessing a specific mode when no reliable signal exists.
- **FR-010**: System MUST leave optional fields empty/unknown when a source does not provide them, and MUST NOT fabricate values (e.g., inventing a salary).
- **FR-011**: System MUST skip and count any individual posting that cannot be normalized because required identity fields are absent, without aborting the rest of the batch.

**Dedup & persistence (monitor semantics)**

- **FR-012**: System MUST assign each job a stable idempotency key: the source's own job identifier when it is stable, otherwise a fallback of title + company + city.
- **FR-013**: System MUST deduplicate jobs both within a single run (including across sources) and across runs by their idempotency key, so a role seen more than once yields exactly one stored record.
- **FR-014**: System MUST persist a never-before-seen job into the existing M1 job store with state "new" and a first-seen timestamp set.
- **FR-015**: System MUST, for a job that already exists in the store, update only its last-seen timestamp and MUST leave its first-seen timestamp and its current state unchanged (never resetting a non-"new" state back to "new").
- **FR-016**: System MUST write all discovered jobs into the single existing M1 job store (not a new or separate store) and MUST reuse an existing store rather than recreating or wiping it.

**Resilience**

- **FR-017**: System MUST isolate each source with its own error handling so that one source erroring, timing out, or being rate-limited does not prevent other sources' results from being processed and does not fail the overall run.
- **FR-018**: System MUST treat partial results (some sources succeeded, some failed) as a valid, successful run.

**Observability** (Constitution Principle VIII)

- **FR-019**: System MUST generate a single run/correlation id per discovery run and thread it through every log line the run emits.
- **FR-020**: System MUST trace each source fetch with at least its start, outcome (success/failure), duration, and the source/endpoint identity, recording call metadata only.
- **FR-021**: System MUST NOT log or transmit the resume, profile, or `prefs.yaml` contents as part of tracing or discovery; only non-personal query/call metadata and public job-posting data are handled by external calls.
- **FR-022**: System MUST emit a per-run summary at run end reporting counts of postings fetched, newly stored, already-seen (updated), skipped (unnormalizable), and per-source failures.
- **FR-023**: System MUST write logs to a tailable, size- or time-rotating log file with a bounded backup count.
- **FR-024**: System MUST surface a run failure via the error-notification channel (ntfy) so a failure in an unattended run is noticed; a single dead source is logged and skipped, not escalated as a whole-run failure.

**Scope guard**

- **FR-025**: System MUST limit this milestone to discover → normalize → dedup → persist-new; it MUST NOT score jobs, apply preference hard-filters beyond building the query, alert on new high-scoring roles, or expose a web board (all deferred to later milestones).

### Key Entities *(include if feature involves data)*

- **Job (canonical record)**: A single normalized job posting stored in the existing job store. Key attributes: idempotency key/identity, source, title, company, location, city, country, work mode (remote/hybrid/onsite/unknown), description, employment type, salary, apply link, state (defaults to "new" for freshly discovered jobs), first-seen / last-seen / updated timestamps. Downstream milestones add score, breakdown, matched skills, and reason.
- **Job Source**: A pluggable provider of postings behind a common interface (JSearch, Adzuna India today; ATS watchlist later). Attributes/behavior: a source name/identity, the ability to run a bounded set of queries and return raw postings, and its own isolated failure handling. New sources conform to the same interface without changing run orchestration.
- **Discovery Run**: One manually-triggered execution that queries the configured sources, normalizes and deduplicates results, persists new jobs, and produces a summary. Attributes: run/correlation id, per-source outcomes, and aggregate counts (fetched, new, seen, skipped, failures).
- **Search Query**: The derived set of search terms/locations used to interrogate sources for a run. Derived from profile roles + seniority crossed with preference locations, overridable by an optional preferences field.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A discovery run against a source turns every returned posting into a canonical job record, with 100% of stored records carrying the required identity fields and a work-mode value (one of remote/hybrid/onsite/unknown).
- **SC-002**: Running discovery twice over identical source results adds zero duplicate records on the second run; 100% of already-seen jobs have their last-seen timestamp advanced while their first-seen timestamp and state are unchanged.
- **SC-003**: When one of two sources fails, the run still completes successfully and stores 100% of the healthy source's new jobs, with the failed source recorded in the run summary.
- **SC-004**: A role returned by two sources in the same run is stored exactly once (single canonical record).
- **SC-005**: Every discovery run produces a per-run summary containing fetched, new, seen, skipped, and per-source-failure counts, and every log line for the run carries the same run/correlation id.
- **SC-006**: No discovery run issues more than the configured bounded number of external requests per source, and repeated identical queries within the freshness window are served from cache without new external calls.
- **SC-007**: No resume, profile, or preferences content appears in any log line or external request payload across a full run (only query metadata and public job data).

## Assumptions

- **Reuses M1 foundations**: The persisted profile, `prefs.yaml`, and the existing SQLite job store (with its `jobs` schema, states, and timestamps) from milestone M1 are present and are reused as-is; this milestone writes into that same store.
- **Manual trigger**: Discovery is invoked manually via the CLI (consistent with v1's no-scheduler stance); automatic scheduling remains a later fast-follow.
- **Search-term source**: By default, search terms are derived from the profile's roles and seniority combined with `prefs.yaml` locations; an optional `search` field in `prefs.yaml` overrides this when the user provides it. (Confirmed decision.)
- **Query bounds default**: Absent explicit user configuration, a small conservative default cap on queries/requests per source per run is applied to respect free-tier limits (e.g., a handful of queries per source, one per location/role combination up to the cap).
- **Cache freshness default**: Cached source responses are considered fresh for a short bounded window (on the order of hours within a day) so same-day re-runs avoid redundant external calls; the exact window is an implementation default.
- **Credentials**: Access keys/credentials for the aggregator sources are supplied via local configuration/environment on the user's machine; this feature assumes they are available and does not manage credential provisioning.
- **Work-mode inference is best-effort**: Text-inferred work mode (for sources lacking an explicit remote flag) is acknowledged as approximate; "unknown" is a valid, honest outcome and is not treated as an error.
- **No preference hard-filtering yet**: Preferences influence discovery only by shaping the search query in this milestone; applying hard filters (company-type, comp floor, seniority gate) and scoring happens in a later milestone and is out of scope here.
- **Privacy boundary**: Only public job-posting text and non-personal query metadata leave the machine via source APIs; personal data (resume, profile, prefs, tracking state) stays local, consistent with the project's privacy principle.
