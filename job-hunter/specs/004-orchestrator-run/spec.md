# Feature Specification: End-to-End Pipeline Orchestrator

**Feature Branch**: `004-orchestrator-run`

**Created**: 2026-07-15

**Status**: Draft

**Input**: User description: "M4 — End-to-end orchestrator (manual CLI trigger). A single `jobhunter run` command that chains the existing M2 discovery/normalize/dedup stage and the M3 filter/score/alert stage into one end-to-end pipeline run: discover → normalize → dedup → filter → score → persist → alert, over the existing SQLite store. Per-source try/except isolation so one dead discovery source never fails the whole run (partial results are valid). A single run/correlation id threaded through every log line for the whole run, with each external/network call traced (start, outcome, duration, source identity — metadata only). An end-of-run summary (per-source discovered/new/deduped counts, filtered_out, scored, alerted) logged at run end and any whole-run failure surfaced via ntfy. Honors filter-before-score, idempotent monitor semantics (no re-alert on already-seen roles), and bounded usage. Manual CLI trigger only — no scheduler in this milestone (launchd is a later fast-follow). Reuses the existing M2 discovery and M3 scoring/alerting modules rather than reimplementing them; adds the orchestration seam and the `run` CLI command with a `--dry-run` flag."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One command runs the whole pipeline (Priority: P1) 🎯 MVP

A job seeker wants to check for new matching roles without remembering a sequence of steps. They trigger a single command. The system discovers jobs from every configured source, normalizes and deduplicates them into the store, then filters and scores the newly-added jobs and alerts on any genuinely new, high-scoring matches — all in one invocation, under one shared run identity, ending with a single summary of what happened.

**Why this priority**: Until M4, discovery and scoring are two separate manual commands the seeker must run in the right order. Chaining them into one dependable command is the whole point of this milestone — it turns a collection of stages into an operable pipeline the seeker can trust and (later) schedule. It delivers value on its own even before the resilience and summary refinements are hardened.

**Independent Test**: With at least one live (or fixtured) discovery source and a valid profile/prefs, trigger the single run command against a store. Verify that jobs are discovered and persisted, that the newly-added jobs are then filtered and scored, that above-threshold new jobs alert, and that the whole sequence completes from a single command without any intermediate manual step.

**Acceptance Scenarios**:

1. **Given** a valid profile, prefs, and at least one working discovery source, **When** the seeker triggers the run command, **Then** discovery, deduplication, filtering, scoring, and alerting all execute in that order and the command reports a combined outcome.
2. **Given** jobs freshly discovered in this run, **When** the scoring stage runs, **Then** it operates on the current contents of the store (the just-discovered new jobs plus any still-unscored jobs from prior runs) rather than requiring a separate command.
3. **Given** the run has completed, **When** the seeker inspects the store, **Then** newly-discovered jobs carry their post-scoring state (filtered-out or scored with a breakdown) exactly as if discovery and scoring had been run separately in sequence.

---

### User Story 2 - One dead source never kills the run (Priority: P2)

A job seeker relies on multiple discovery sources, any of which can fail transiently (rate limit, outage, network blip). When one source fails, they still want the roles from the healthy sources to flow all the way through to a scored shortlist — a partial result is far more useful than an aborted run.

**Why this priority**: An unattended monitor that aborts wholesale whenever any single source hiccups is untrustworthy. Per-source isolation is what makes the pipeline dependable enough to eventually schedule. It builds on US1 but is separable — the pipeline can chain end-to-end (US1) before failure isolation is proven.

**Independent Test**: Configure two discovery sources where one deterministically fails; trigger the run. Verify the failing source is recorded as failed, the healthy source's jobs are still discovered, deduplicated, filtered, and scored, and the run completes successfully with the failure noted rather than raising.

**Acceptance Scenarios**:

1. **Given** two configured sources where one fails, **When** the run executes, **Then** the healthy source's jobs proceed through the full pipeline and the run finishes successfully.
2. **Given** a source that fails during discovery, **When** the run finishes, **Then** that source's failure is captured in the run outcome (which source and a reason) rather than being silently dropped.
3. **Given** every discovery source fails, **When** the run executes, **Then** the run does not raise; scoring still runs over any pre-existing unscored jobs in the store and the outcome reflects that no new jobs were discovered.

---

### User Story 3 - A run I can see into and be warned about (Priority: P3)

Because the seeker will eventually let this run unattended, every run must tell a coherent, reconstructable story: one identity ties together everything that happened, an end-of-run summary states what was discovered, filtered, scored, and alerted, and any failure that stops the whole run reaches the seeker on their phone so a silent stop is impossible.

**Why this priority**: Observability is what makes an unattended monitor believable. Without a single run identity, a per-run summary, and an error signal, a failed or misbehaving run goes unnoticed until the seeker wonders why no roles have surfaced. It layers onto US1/US2 and is independently demonstrable.

**Independent Test**: Trigger a run and inspect its logs and summary; verify every line of that run shares one correlation identity, each external call is traced with its outcome and duration (and no personal content), and the end-of-run summary reports per-source discovered/new/deduped counts plus filtered-out, scored, and alerted totals. Separately, force a whole-run failure and verify an error notification is sent.

**Acceptance Scenarios**:

1. **Given** a run in progress, **When** its log output is examined, **Then** every line emitted by that run carries the same run/correlation identity, so one run's activity can be isolated end to end.
2. **Given** the run makes external calls (discovery sources, any provider call), **When** those calls are traced, **Then** each trace records start, outcome, duration, and source/endpoint identity — and never the resume, prefs, profile, or any personal payload.
3. **Given** the run completes, **When** the end-of-run summary is produced, **Then** it reports per-source discovered/new/deduped counts alongside filtered-out, scored, and alerted totals for the run.
4. **Given** an error that aborts the whole run (not an isolated single-source failure), **When** it occurs, **Then** an error notification is pushed to the seeker's alert channel.

---

### User Story 4 - Rehearse a run without touching anything (Priority: P4)

Before letting the pipeline write to the store and fire alerts — for example after editing prefs or adding a source — the seeker wants to rehearse a full run to see what *would* happen, with no persisted changes and no notifications sent.

**Why this priority**: A safe rehearsal builds confidence in configuration changes and is a prerequisite for trusting the pipeline enough to schedule it later. It is the lowest priority because the pipeline is fully functional without it; it is a safety affordance, not a core capability.

**Independent Test**: Trigger the run in rehearsal mode against a known store; verify the summary reflects what would have happened, no job records are written or modified, and no alerts are sent.

**Acceptance Scenarios**:

1. **Given** the seeker triggers a run in rehearsal mode, **When** it completes, **Then** the store is unchanged (no new jobs persisted, no states transitioned, no alert timestamps stamped) and no notifications are sent.
2. **Given** a rehearsal run, **When** the summary is produced, **Then** it still reports the counts the run would have produced, so the seeker can judge the effect before committing to it.

---

### Edge Cases

- **No configured sources / empty query**: The run completes as a clean no-op (nothing discovered), still emits a run identity and summary, and does not raise.
- **Discovery succeeds but adds zero new jobs**: Scoring still runs over any pre-existing unscored jobs; if there are none, the run is a clean no-op with a zero-count summary.
- **Missing profile or prefs**: The run fails fast with a clear error before doing any external work (nothing to discover or score against), and that whole-run failure is surfaced as an error signal.
- **Alerting cap reached mid-run**: The per-run alert cap and the never-re-alert guarantee from the scoring milestone continue to hold when invoked through the orchestrator — the orchestrator must not cause a role to be alerted twice or exceed the cap.
- **Rehearsal mode with a failing source**: Source isolation still applies; the failure is reported in the summary but nothing is persisted and nothing is sent.
- **Interruption partway through**: Because each stage persists through the store as it goes (outside rehearsal mode), a re-run is idempotent — already-seen roles are not re-alerted and already-scored roles are not rescored into a duplicate alert.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a single manually-triggered command that runs the full pipeline — discover → normalize → deduplicate → filter → score → persist → alert — end to end in one invocation.
- **FR-002**: The orchestrator MUST reuse the existing discovery stage and the existing filter/score/alert stage rather than reimplementing their logic; it composes them into one run.
- **FR-003**: The stages MUST execute in an order that preserves filter-before-score — no scoring or heavier work runs on a job before the cheap hard-filter gate has been applied.
- **FR-004**: A single discovery source failing MUST NOT abort the run; the failure MUST be isolated, recorded, and skipped, and the remaining sources' results MUST continue through the pipeline (partial results are valid results).
- **FR-005**: The run MUST preserve idempotent monitor semantics: a re-run MUST update already-seen roles' last-seen tracking without re-alerting them, and MUST NOT rescore-then-re-alert a role that was already alerted.
- **FR-006**: The run MUST honor the configured alert threshold and the per-run alert cap, and MUST alert only on genuinely new roles scoring at or above the threshold — the orchestrator MUST NOT weaken or bypass these guarantees.
- **FR-007**: The system MUST generate one run/correlation identity per run and thread it through every log line the run emits, so a single run's activity can be isolated end to end across both stages.
- **FR-008**: Every external/network call made during the run (each discovery source and any provider call) MUST be traced with at least its start, outcome (success/failure), duration, and source/endpoint identity.
- **FR-009**: Traces and logs MUST record call metadata only — never the resume text, prefs, profile, or any personal payload.
- **FR-010**: The system MUST produce and log an end-of-run summary reporting per-source discovered/new/deduplicated counts together with filtered-out, scored, and alerted totals for the run.
- **FR-011**: A failure that aborts the whole run (as distinct from an isolated single-source failure) MUST be surfaced to the seeker via the error-notification channel.
- **FR-012**: The system MUST support a rehearsal (dry-run) mode that exercises the full pipeline without persisting any store changes and without sending any alerts, while still reporting the counts the run would have produced.
- **FR-013**: The run MUST keep LLM/provider usage bounded exactly as the underlying stages define it — the orchestrator MUST NOT introduce any additional, unbounded, or per-job-independent LLM usage.
- **FR-014**: This milestone MUST NOT introduce an automatic scheduler; the run is manually triggered only (scheduling is a later fast-follow).
- **FR-015**: When there is nothing to do (no sources, empty query, or no unscored jobs), the run MUST complete cleanly as a no-op with a zero-count summary rather than erroring.

### Key Entities *(include if feature involves data)*

- **Pipeline Run**: One end-to-end execution of the orchestrator. Carries a single run/correlation identity, the rehearsal-vs-real mode, and the ordered composition of the discovery stage and the scoring/alerting stage. It owns no new persisted state of its own — it drives the existing job store through the existing stages.
- **Run Outcome / Summary**: The aggregate report of one run — per-source discovered/new/deduplicated counts, the set of source failures (source → reason), and filtered-out/scored/alerted totals — logged at run end and printed to the seeker. Composed from the two existing stage summaries under one run identity.
- **Job (existing)**: The stored role record the pipeline reads and advances (discovered → deduplicated → filtered-out or scored → optionally alerted). Unchanged by this feature except that its state now advances within a single orchestrated run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A seeker can go from "nothing" to a freshly-scored shortlist with new-role alerts using exactly one command, with zero intermediate manual steps.
- **SC-002**: When one of multiple discovery sources fails, 100% of the healthy sources' discovered roles still complete the full pipeline through scoring, and the run reports success with the failure noted.
- **SC-003**: Every log line produced by a run is attributable to that run via a single shared correlation identity, so one run's story can be reconstructed end to end from the log.
- **SC-004**: The end-of-run summary lets the seeker see, at a glance and without any extra query, how many roles were discovered, deduplicated, filtered out, scored, and alerted in the run.
- **SC-005**: Across two consecutive runs over the same above-threshold role, exactly one alert is sent total — the orchestrated re-run never re-alerts an already-seen role.
- **SC-006**: A whole-run failure always reaches the seeker as an error notification; no run stops silently.
- **SC-007**: A rehearsal run leaves the store byte-for-byte unchanged and sends zero notifications, while still reporting the counts it would have produced.

## Assumptions

- **Stages already exist and are trusted**: The discovery/normalize/dedup stage (M2) and the filter/score/alert stage (M3), including their per-source isolation, their run-summary shapes, and their alerting guarantees, are complete and correct; M4 composes them and does not re-verify their internal logic beyond the seam.
- **Scoring scope within a run**: The scoring stage operates over the store's current unscored ("new") jobs — i.e. this run's freshly-discovered jobs plus any still-unscored leftovers from prior runs — matching the existing scoring stage's behavior rather than tracking a per-run set.
- **Shared run identity is already available**: The observability layer already exposes a per-run correlation identity that both existing stages reuse; the orchestrator establishes it once for the whole run so both stages log under the same identity.
- **Alerting is per-role, not per-run-completion**: Individual new-high-scorer alerts are emitted by the scoring/alerting stage during the run; the orchestrator's own notification responsibility is limited to surfacing a whole-run failure.
- **Manual trigger only**: No scheduling mechanism (e.g. launchd/cron) is introduced in this milestone; that is an explicitly deferred fast-follow.
- **Same store and configuration**: The run reads the existing profile, prefs, and SQLite store already established by prior milestones; no new configuration surface or schema change is required by this feature.
- **Rehearsal mode composes the stages' existing dry-run behavior**: Both underlying stages already support a no-write mode; the orchestrator's rehearsal mode propagates it rather than inventing separate semantics.
