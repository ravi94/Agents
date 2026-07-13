# Feature Specification: Job Scoring, Filtering & Alerting

**Feature Branch**: `003-job-scoring-filtering`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "M3 — Job Scoring, Filtering & Alerting. Apply cheap hard filters (location, work mode, company type, comp/seniority floor) from prefs.yaml before any heavier scoring work, then compute a composite soft-weighted score for each surviving job against prefs.yaml weights and profile.json skills/experience, persisting the full breakdown (component scores, matched skills, why-matched) alongside each job. Optionally re-rank the top ~25 survivors via a bounded LLM call for a qualitative reason string. Notify the user via ntfy only when a genuinely new job (state=new) scores above the configured alert threshold — reruns must never re-alert on already-seen jobs. Scope is filter→score→(optional re-rank)→alert only; the web triage board and any tracking/pipeline states beyond scoring are later milestones."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Filter and score newly discovered jobs (Priority: P1) 🎯 MVP

A job seeker has jobs sitting in the store with state "new" from a discovery run. They trigger scoring. The system first applies cheap hard filters (location, work mode, company type, comp floor, seniority floor) drawn from the seeker's `prefs.yaml`; any job that fails a hard filter is excluded from further processing. Every job that survives is scored against the seeker's soft-weighted preferences and their profile's skills/experience, and the resulting score — along with a full breakdown of what drove it — is persisted alongside the job.

**Why this priority**: Discovery (M2) only fills the store; nothing downstream is useful until jobs are separated from noise and ranked. Filtering and scoring is the foundational step that turns a raw inventory into a shortlist, and it delivers value on its own even before alerting or re-ranking exist.

**Independent Test**: Seed the store with a mix of jobs — some that fail at least one hard filter, some that pass all of them — and run the scoring step. Verify filtered-out jobs are excluded from the scored output, every surviving job has a persisted numeric score, and the run reports counts of filtered-out vs. scored jobs.

**Acceptance Scenarios**:

1. **Given** a job that fails a hard filter (e.g., wrong work mode), **When** scoring runs, **Then** the job is marked as filtered out, receives no score, and is excluded from any later alerting or ranking.
2. **Given** a job that passes every hard filter, **When** scoring runs, **Then** the job receives a composite score computed from the seeker's soft weights and profile skills/experience, and that score is persisted on the job record.
3. **Given** a job missing an optional data point needed by one hard filter (e.g., no listed salary for the comp floor), **When** scoring runs, **Then** the job is not auto-rejected for that missing data alone — it proceeds to scoring with that dimension treated as unknown.

---

### User Story 2 - Explainable score breakdown (Priority: P2)

Having received a score, the seeker wants to know *why* a job ranked where it did rather than trust an opaque number. For every scored job, the system persists and can surface the component scores (one per soft-weight category) and the specific matched skills that contributed, so the seeker can audit and eventually tune their preferences.

**Why this priority**: Trust in the shortlist depends on explainability; a bare score with no reasoning is not actionable and undermines the copilot's core value proposition. It builds directly on US1's scoring but is separable — scoring can technically run without a human-readable breakdown, though it shouldn't ship that way.

**Independent Test**: Score a job with a known profile and prefs fixture; verify the persisted record includes per-component scores that sum/roll up to the overall score, and a list of matched skills, both retrievable without recomputation.

**Acceptance Scenarios**:

1. **Given** a scored job, **When** its record is inspected, **Then** the breakdown shows a score per soft-weight component (not just the total) and the specific skills from the profile that matched the job's requirements.
2. **Given** two jobs with the same overall score, **When** their breakdowns are compared, **Then** the differing component contributions are visible, explaining how each arrived at the same total by a different path.
3. **Given** a desirability signal that is a proxy rather than a direct measurement (e.g., work-life balance inferred from company type), **When** it appears in the breakdown, **Then** it is labeled as inferred rather than presented as a directly observed fact.

---

### User Story 3 - Alert only on genuinely new, high-scoring jobs (Priority: P3)

The seeker wants to be notified when something worth their attention appears, without being buried in repeat noise. After scoring, the system sends a single notification only for jobs that are both genuinely new (never alerted on before) and score at or above the seeker's configured alert threshold. A job that continues to score above threshold on later runs does not trigger a second alert.

**Why this priority**: Alerting is what turns a passive store into an active copilot, but it depends entirely on filtering and scoring already existing (US1) and ideally the breakdown (US2) so the alert can reference why the job qualified. It is the last mile of this milestone, not its foundation.

**Independent Test**: Run scoring twice over the same job (score above threshold both times); verify exactly one notification fires across both runs. Separately, verify a job scoring below threshold never triggers a notification regardless of how many times it's rescored.

**Acceptance Scenarios**:

1. **Given** a job newly scored above the alert threshold, **When** scoring completes, **Then** the seeker receives one notification referencing that job.
2. **Given** a job already notified on in a prior run, **When** it is rescored in a later run and still scores above threshold, **Then** no additional notification is sent.
3. **Given** a job scoring below the alert threshold, **When** scoring completes, **Then** no notification is sent for it, regardless of how many hard filters it passed.
4. **Given** no notification channel is configured, **When** a job qualifies for an alert, **Then** scoring still completes and the score/breakdown is still persisted — only the notification step is skipped.

---

### User Story 4 - Optional qualitative re-rank of top survivors (Priority: P4)

For the small set of top-scoring jobs, the seeker wants a qualitative second opinion beyond the mechanical score — a short reason describing fit in plain language. The system may optionally send the top ~25 scored survivors through a single bounded call to re-rank or annotate them, attaching that reasoning to the persisted breakdown without being a precondition for scoring or alerting to work.

**Why this priority**: This is a genuine enhancement but the lowest priority — the pipeline is fully functional and trustworthy (filtered, scored, explained, alerted) without it. It's an optional refinement layered on top of US1–US3.

**Independent Test**: Run scoring with re-rank enabled against a fixture of 25+ survivors; verify only the top ~25 receive an attached reason string, exactly one bounded call is made regardless of survivor count, and disabling re-rank leaves scoring/alerting fully functional.

**Acceptance Scenarios**:

1. **Given** more than 25 scored survivors, **When** re-rank runs, **Then** only the top ~25 by score are sent for annotation, and the call count for the run does not scale with total survivor count.
2. **Given** re-rank is disabled or fails/times out, **When** scoring runs, **Then** the base score and breakdown are still persisted and alerting still functions unaffected.
3. **Given** a re-ranked job, **When** its breakdown is inspected, **Then** the qualitative reason string is stored alongside (not in place of) the mechanical component scores.

---

### Edge Cases

- What happens when `prefs.yaml`'s soft weights don't sum to ~1.0 (already flagged as a warning at `prefs validate` time)? Scoring MUST use the weights as configured, not silently renormalize them.
- What happens when a job already carries a user-set state beyond "new" (e.g., "interested", "rejected") from manual triage? Rescoring MUST NOT overwrite that state or re-trigger an alert for it.
- What happens when every job in a run fails at least one hard filter? The run completes with zero scored jobs and reports the filtered-out count — this is not an error condition.
- What happens when the optional LLM re-rank call errors or times out? The run MUST still complete with base scores/breakdowns persisted and alerts sent as normal; only the qualitative reason is absent.
- What happens when a job's score changes across reruns (e.g., prefs were edited) but it was already alerted on? It MUST NOT re-alert, per the Monitor principle — even though the underlying number changed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST apply hard filters (location, work mode, company type, comp floor, seniority floor) sourced from `prefs.yaml` to every job in state "new" before any scoring is attempted.
- **FR-002**: A job that fails any hard filter MUST be excluded from scoring and alerting, and MUST be marked in a way that distinguishes it from scored jobs.
- **FR-003**: A job missing the specific data point a hard filter checks (e.g., no salary listed) MUST NOT be auto-rejected for that missing data alone; that filter dimension MUST be treated as unknown/pass-through.
- **FR-004**: For every job that passes all hard filters, System MUST compute a single composite score using the soft weights in `prefs.yaml` against the skills/experience in `profile.json` and the job's own attributes.
- **FR-005**: System MUST persist the full score breakdown alongside each scored job — at minimum, the per-component (per soft-weight) scores and the specific matched skills — not the overall score alone.
- **FR-006**: System MUST make the score breakdown inspectable so the reason a job ranked where it did is auditable; an overall score MUST NOT be surfaced without its accompanying breakdown.
- **FR-007**: Any breakdown component that is an inferred/proxy signal (e.g., work-life balance inferred from company type) MUST be labeled as inferred, not presented as directly measured.
- **FR-008**: System MUST send a notification only for a job that is both never-before-alerted and currently scored at or above the seeker's configured alert threshold.
- **FR-009**: System MUST record that a job has been alerted on so that later runs never send a second notification for the same job, regardless of subsequent rescoring.
- **FR-010**: System MUST NOT fail the run when no notification channel is configured — scoring and persistence MUST complete regardless, with only the notification step skipped.
- **FR-011**: System MAY optionally re-rank the top ~25 scored survivors per run via a single bounded call, attaching a qualitative reason string to each survivor's persisted breakdown.
- **FR-012**: The optional re-rank MUST NOT be a precondition for scoring, breakdown persistence, or alerting — disabling it or having it fail/time out MUST leave the rest of the pipeline fully functional.
- **FR-013**: Rescoring MUST NOT overwrite a job's state if it has already progressed beyond "new"/"filtered-out" (e.g., a seeker-set state from manual review).
- **FR-014**: Scoring MUST be triggerable independently of discovery, so a seeker can rescore existing jobs (e.g., after editing `prefs.yaml`) without re-running discovery.
- **FR-015**: Each scoring run MUST report a per-run summary — counts of filtered-out, scored, and alerted jobs.

### Key Entities

- **Score Breakdown**: Persisted per job — overall composite score, one score per soft-weight component, the list of matched skills, an optional qualitative re-rank reason, and the timestamp it was computed.
- **Filter Result**: Per-job outcome of the hard-filter pass — whether it passed, and if not, which filter(s) it failed — used to gate whether a job proceeds to scoring.
- **Alert Record**: Tracks which jobs have already triggered a notification, preventing duplicate alerts across reruns.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After a scoring run, zero jobs that failed a hard filter appear among the scored or alerted output.
- **SC-002**: For every scored job, a seeker can identify the specific factors (matched skills, weighted categories) that drove its score, with no job showing a bare number and no breakdown.
- **SC-003**: Across any number of reruns where a job's score remains above the alert threshold, the seeker receives at most one notification for that job.
- **SC-004**: A seeker reviewing the shortlist can identify the top contributing factor behind the highest-ranked job's score without cross-referencing external notes.
- **SC-005**: When the optional re-rank is enabled, a scoring run makes no more than one bounded qualitative-annotation call regardless of how many jobs were scored.

## Assumptions

- `prefs.yaml`'s hard filters, soft weights, and alert threshold (established in M1) are already defined and valid; this milestone consumes that schema rather than changing it.
- `profile.json` (from M1) already supplies the skills/experience used as scoring input; this milestone does not change how the profile is built.
- Scoring operates on jobs already persisted by M2's `discover` command; no new discovery sources are introduced here.
- The optional LLM re-rank reuses the existing swappable provider interface and stays within the bounded top-~25-per-run usage already committed to project-wide.
- Alerting continues to use the existing local notification channel already wired up for run failures, rather than introducing a new channel.
- The web triage board and any tracking states beyond new/filtered-out/scored (e.g., applied, interviewing) are out of scope for this milestone and deferred to a later one.
