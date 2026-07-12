# Feature Specification: Resume Profile & Preferences Foundation

**Feature Branch**: `001-resume-profile-prefs`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "Resume parsing to structured profile, prefs.yaml schema, and SQLite schema (job-hunt copilot M1). Users provide a resume PDF once; the system extracts a structured candidate profile (skills, experience, seniority, roles) from it and persists it so it isn't re-parsed on every run. Users also maintain a hand-editable prefs.yaml describing hard filters (locations, work modes, company types allow/deny, comp floor, seniority floor) and soft weights (work-life balance, stability, scope, comp) used later for scoring, seeded initially via a short one-time guided interview. The system also establishes the persistent jobs data store that will hold discovered jobs, their scores, and triage/tracking state in later features. This is the foundational milestone (M1) of the job-hunt copilot; downstream discovery, scoring, and tracking features build on the Profile, preferences, and job store produced here."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Turn a resume into a reusable profile (Priority: P1)

A job seeker provides their resume (PDF) once. The system reads it and produces a structured profile capturing their skills, work experience, seniority level, and past roles. That profile is saved so future runs of the copilot can reuse it without re-processing the resume.

**Why this priority**: Every downstream feature (matching, scoring, ranking) needs a structured profile to compare jobs against. Without this, nothing else in the copilot can function. This is the single most foundational capability.

**Independent Test**: Can be fully tested by supplying a resume PDF and verifying a structured profile (skills, experience, seniority, roles) is produced and persisted, and that a second run does not require re-supplying or re-processing the resume.

**Acceptance Scenarios**:

1. **Given** a user has a resume PDF and no profile exists yet, **When** they submit the resume to the system, **Then** the system produces a structured profile containing at least skills, experience history, seniority level, and roles, and saves it for future use.
2. **Given** a profile has already been created from a resume, **When** the copilot runs again, **Then** the system uses the saved profile without asking the user to resupply the resume or reprocessing it.
3. **Given** a user wants to update their profile (e.g., after a resume revision), **When** they submit a new resume, **Then** the system replaces the previously saved profile with a newly derived one.

---

### User Story 2 - Define what "a good match" means via preferences (Priority: P2)

A job seeker sets up their matching preferences: hard filters (locations, work modes, company types to allow/deny, minimum compensation, minimum seniority) that immediately rule roles in or out, and soft weights (work-life balance, stability, scope, compensation) that will later tune how surviving roles are ranked. The system seeds this the first time via a short guided interview, and afterward the preferences remain a plain, hand-editable file the user can revise anytime without going through the interview again.

**Why this priority**: Hard filters and soft weights are what make the copilot personalized rather than a generic job list; scoring and filtering (built in later milestones) depend entirely on this data existing in a well-defined shape. It's second only to having a profile to match against.

**Independent Test**: Can be fully tested by completing the one-time guided interview and verifying a preferences file is created with the expected hard-filter and soft-weight fields populated; and separately, by hand-editing that file and verifying the system picks up the change without re-running the interview.

**Acceptance Scenarios**:

1. **Given** a first-time user with no preferences set, **When** they run the guided interview, **Then** the system produces a preferences file containing hard filters (locations, work modes, company-type allow/deny lists, compensation floor, seniority floor) and soft weights (work-life balance, stability, scope, compensation) with values reflecting their answers.
2. **Given** a preferences file already exists, **When** the copilot runs, **Then** the system does not prompt the guided interview again and instead uses the existing file.
3. **Given** a user directly edits a value in the preferences file (e.g., changes the compensation floor), **When** the copilot next reads preferences, **Then** it uses the updated value without requiring the guided interview to be re-run.
4. **Given** a user provides soft weights, **When** the preferences are saved, **Then** the system does not silently alter the user's chosen weight values (it may flag if they are unusual, but must preserve user intent).

---

### User Story 3 - Establish a durable place to track jobs over time (Priority: P3)

The system establishes a persistent store capable of holding every job the copilot will discover in future runs, along with each job's score and its triage/tracking state, so that later milestones (discovery, scoring, triage board) have a durable foundation to write to and read from rather than each inventing their own storage.

**Why this priority**: This is purely foundational and has no directly observable behavior on its own until discovery and scoring features (later milestones) exist to populate it — hence lowest priority — but it is a prerequisite structural piece that must exist before those features can be built.

**Independent Test**: Can be fully tested by verifying the store can accept a record representing a job (with its identifying details, a score placeholder, and a triage/tracking state) and can retrieve that same record back unchanged, and that the store persists across separate copilot runs (i.e., is not wiped or recreated each time).

**Acceptance Scenarios**:

1. **Given** the copilot has never been run before, **When** it is run for the first time, **Then** a persistent job store is created if one does not already exist.
2. **Given** the job store already exists from a previous run, **When** the copilot runs again, **Then** the existing store and its contents are reused, not recreated or wiped.
3. **Given** a record is written to the store representing a job, **When** it is later read back, **Then** all of its fields (identity, score placeholder, triage/tracking state, timestamps) are returned unchanged.

---

### Edge Cases

- What happens when the submitted resume is not a valid/parseable PDF, or is a scanned image with no extractable text?
- What happens when the resume is missing information needed for a complete profile (e.g., no explicit seniority level stated)?
- How does the system handle a preferences file that a user has hand-edited into an invalid state (e.g., soft weights that don't sum close to 1.0, an unrecognized work mode, a negative compensation floor)?
- What happens if the guided interview is interrupted partway through (e.g., the user quits before answering all questions)?
- What happens when the profile-generation step fails partway (e.g., the parsing dependency is unavailable) — does the user get a clear error, and is any previously saved profile left intact rather than corrupted?
- What happens when two hard filters conflict or produce an empty result space (e.g., compensation floor higher than seniority floor typically pays)?
- What happens when the job store is queried for a job identity that hasn't been written yet?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a resume in PDF form as input for one-time profile creation.
- **FR-002**: System MUST derive a structured profile from the resume containing, at minimum: skills, work experience history, seniority level, and past roles.
- **FR-003**: System MUST persist the derived profile so it is available to future copilot runs without requiring the resume to be resubmitted or reprocessed.
- **FR-004**: System MUST allow the user to replace the saved profile by submitting a new resume, which fully supersedes the previous profile.
- **FR-005**: System MUST provide a one-time guided interview that collects the information needed to seed a preferences file for first-time users.
- **FR-006**: System MUST produce a preferences file containing hard filters (locations, work modes, company-type allow list, company-type deny list, compensation floor, seniority floor) and soft weights (work-life balance, stability, scope, compensation).
- **FR-007**: System MUST treat the preferences file as the durable source of user preferences: once created, it MUST be human-readable and hand-editable, and the system MUST honor manual edits on subsequent runs without requiring the guided interview to be repeated.
- **FR-008**: System MUST NOT overwrite user-hand-edited preference values on a normal run (the guided interview is only for initial seeding or an explicit user-triggered re-run).
- **FR-009**: System MUST establish a persistent store for job records before any discovery, scoring, or tracking feature (built in later milestones) can write to it.
- **FR-010**: The job store MUST retain a stable identity, a score placeholder, a triage/tracking state, and first-seen/last-seen timestamps per job record, so future milestones can populate and update these fields without redefining the record shape.
- **FR-011**: The job store MUST persist across separate copilot runs (i.e., data is not lost or reset between runs).
- **FR-012**: System MUST surface a clear, actionable error to the user when resume parsing fails (e.g., unreadable PDF), without leaving a partially-written or corrupted profile behind.
- **FR-013**: System MUST validate a hand-edited preferences file on load and surface a clear error identifying which field is invalid when values are malformed (e.g., unrecognized work mode, negative compensation floor) rather than silently accepting or discarding them.
- **FR-014**: System MUST keep the resume, the derived profile, and the preferences file on the user's own machine; none of this data is transmitted to any party other than what is strictly necessary to derive the profile from resume text.

### Key Entities

- **Profile**: The structured representation of the candidate derived from their resume. Attributes include skills, work experience history, seniority level, and past roles. One profile exists per user at a time; a new resume submission replaces it.
- **Preferences**: The user's hand-editable matching configuration. Contains hard filters (locations, work modes, company-type allow/deny lists, compensation floor, seniority floor) that gate which jobs are considered, and soft weights (work-life balance, stability, scope, compensation) that will tune ranking in later milestones. Seeded once via a guided interview, then user-owned.
- **Job Record (store schema only)**: The durable unit later milestones will populate — one per discovered job — carrying a stable identity, source, descriptive fields, a score placeholder, a triage/tracking state, and first-seen/last-seen timestamps. This feature establishes the store and its shape; populating it with real discovered jobs is out of scope here.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from "have a resume PDF" to "have a saved, structured profile" in a single submission, without manual data entry of their skills or experience.
- **SC-002**: On every copilot run after the first, the previously saved profile is reused automatically — 0 additional resume submissions required per run.
- **SC-003**: A first-time user can complete the guided interview and get a usable preferences file in under 5 minutes.
- **SC-004**: 100% of hand-edits a user makes to their preferences file are honored on the next run without any guided interview being re-triggered.
- **SC-005**: The job store retains all written records with zero data loss across at least 100 consecutive copilot runs.
- **SC-006**: A user encountering an unparseable resume or an invalid preferences edit receives an error message that identifies the specific problem, on the first attempt, without needing to inspect logs.

## Assumptions

- The resume is provided in English and in a text-extractable PDF format; OCR of scanned/image-only resumes is out of scope for this feature.
- Exactly one profile and one preferences file exist per installation (single-user, local use), consistent with the copilot's local-first, single-user design.
- The guided interview runs once for initial preferences seeding; a user wanting to fully redo it (rather than hand-edit) can explicitly re-trigger it, but this is not a repeated/scheduled behavior.
- "Persistent store" in User Story 3 refers only to establishing the durable structure and read/write capability for job records; discovering real jobs, scoring them, and the triage/tracking UI are out of scope and covered by later milestones (M2–M5).
- Soft weights are expected to sum to approximately 1.0 as guidance, not a hard-enforced constraint, consistent with the preferences shape described in the project's high-level design.
- No multi-user access control, authentication, or sharing is in scope; the system runs for a single local user.
