<!--
Sync Impact Report
Version change: 2.2.0 → 2.3.0
Rationale: Added an Observability principle (structured log tracing with a run
correlation id, log-file rotation to bound disk, and per-feature monitoring via
a tailable log plus ntfy-on-error) at the user's request. A new principle is a
MINOR bump per this document's own versioning policy. The principle is scoped to
stay local-first and zero-cost (stdlib logging + RotatingFileHandler; no hosted
observability service) and privacy-preserving (trace call metadata — durations,
outcomes, source ids — never resume/prefs payloads, per Principle I).
Modified principles: none
Added sections:
  - VIII. Observable by Default (Tracing, Rotation & Monitoring)
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md ✅ reviewed — Constitution Check gate is a
    generic fill-in ("[Gates determined based on constitution file]"); no edit needed
  - .specify/templates/spec-template.md ✅ reviewed — observability is an operational
    concern, not a spec-level mandatory section; no edit needed
  - .specify/templates/tasks-template.md ⚠ updated — foundational logging task and
    per-story logging task now name structured tracing (run id), log rotation, and
    error/health signal surfacing, so generated task lists carry the new principle
Deferred TODOs: none

Prior amendment (2.1.0 → 2.2.0): added VII. Test-First Development (NON-NEGOTIABLE);
tasks-template updated to make per-story tests mandatory rather than opt-in.
-->

# Job-Hunt Copilot Constitution

## Core Principles

### I. Explicit LLM Provider Boundaries (Local-First Target)
Every LLM text-generation touchpoint (resume structuring, optional re-rank) MUST sit
behind a swappable provider interface so the calling code is identical regardless of
provider. v1 MVP MAY default this interface to the Claude Code CLI (`claude -p`,
non-interactive mode), authenticated via the user's existing Claude Pro subscription
login — MUST NOT use metered Anthropic API-key billing, since none is provisioned.
Migrating the default to the local Ollama stack (Qwen2.5) is a committed, tracked
fast-follow — not a someday-maybe. Embeddings MUST always run locally via Ollama
(`mxbai-embed-large`), in both the MVP and fast-follow phases: this piece was already
free and private, and Claude has no embeddings endpoint to swap to. Whichever
text-generation provider is active, calls to it MUST be limited to the minimum content
needed for that call (resume text, job description text) — `prefs.yaml`, tracking
state, and any other personal data MUST NOT be sent to a third-party provider under
any configuration.
**Rationale:** A hosted model gets v1 working faster and at higher initial quality
than tuning a local prompt from scratch, and the CLI-via-Pro-subscription path is
Anthropic's officially supported mechanism for exactly this kind of scripted personal
use; committing to the local swap up front (rather than leaving it open-ended) keeps
the eventual privacy promise from quietly slipping.

### II. Bounded Usage, Zero Incremental Cost
LLM usage MUST stay small and visible: resume parsing runs once per resume, and
re-rank is bounded to the top ~25 survivors per run, executed manually (not
continuously) in v1. Because MVP reuses the user's already-owned Claude Pro
subscription rather than metered API billing, v1 introduces **zero incremental
spend** — but that usage draws from a quota shared with the user's ordinary
claude.ai usage, so run volume MUST stay bounded to avoid crowding it out. Migrating
structuring/re-rank to the local Ollama stack is a committed fast-follow that removes
this shared-quota dependency entirely, not a permanent state. Discovery (JSearch,
Adzuna) MUST continue to rely on free tiers regardless of LLM provider. No feature may
introduce open-ended, unbounded, or per-job-independent LLM usage.
**Rationale:** The project targets zero ongoing cost on infrastructure the user
already pays for; reusing an existing subscription — instead of provisioning metered
API billing — achieves that target directly rather than treating it as a bootstrap
expense.

### III. Ethical Boundaries (NON-NEGOTIABLE)
The system MUST NEVER auto-apply to a role on the user's behalf. The system MUST NEVER
scrape LinkedIn or any source in violation of its terms. Aggregator rate limits MUST be
respected: bounded queries per run, response caching, and backoff on HTTP 429. A human
MUST remain the actor for every application decision.
**Rationale:** These are hard lines that protect the user's reputation and accounts and
keep the tool on the right side of platform terms; convenience never justifies crossing
them.

### IV. Monitor, Not Search (Idempotent State)
The system is a monitor over a persistent store, not a stateless search. Every job MUST
carry a stable idempotency key (source id when stable, else `title|company|city`).
Reruns MUST update `last_seen` and MUST NOT re-alert on already-seen roles. The user MUST
be notified ONLY on genuinely new roles scoring above the configured threshold.
**Rationale:** Duplicate alerts destroy signal; the difference between a useful copilot
and noise is remembering what has already been shown.

### V. Explainable Ranking
Every score MUST persist its full breakdown (component scores, matched skills, and any
re-rank reason) alongside the job. The triage surface MUST show *why* a role ranked where
it did. The system MUST NOT surface an opaque number. Where a desirability signal is a
proxy (e.g. WLB inferred from company-type), that MUST be represented honestly rather than
presented as a direct measurement.
**Rationale:** Trust in the shortlist depends on the user being able to audit and tune
ranking; unexplained scores cannot be improved or believed.

### VI. Deterministic Simplicity (YAGNI)
v1 MUST be a deterministic Python pipeline with no agent framework, regardless of which
LLM provider is behind Principle I. LLM touchpoints are limited to (a) one-time resume
structuring and (b) an optional top-shortlist re-rank; all other stages MUST be plain,
testable Python. New sources MUST implement the common `JobSource` interface. Complexity —
agent loops, ML weight learning, additional services — MUST be deferred until a concrete
need is proven, and any such addition MUST be justified against this principle.
**Rationale:** The v1 flow has no genuine branching; a framework would add latency and
operational surface for no benefit, and simplicity keeps the spine debuggable.

### VII. Test-First Development (NON-NEGOTIABLE)
For every unit of behavior, a test MUST be written first, MUST be reviewed, and MUST
be observed to fail before the corresponding implementation is written (red-green-
refactor). This applies to all deterministic logic without exception: hard filters,
dedup, the composite scoring math, the normalizer, state transitions, and API
endpoints. For LLM-touching code (resume parser, re-rank), tests MUST target the
surrounding plumbing rather than the model itself: JSON-schema/contract validation of
provider responses, error handling (malformed output, timeouts, provider failures),
and the provider-swap interface (Principle I) — all via mocked or fixture responses.
Tests MUST NOT assert on exact LLM wording, and a live model call MUST NOT be a
condition of a test passing.
**Rationale:** TDD catches scoring/filtering regressions — the ones that silently
corrupt rankings — before they ship. Since LLM output is inherently non-deterministic,
what must be verified mechanically is the contract around the model, not its wording;
testing prose would make the suite flaky for no safety gained.

### VIII. Observable by Default (Tracing, Rotation & Monitoring)
Every feature MUST be observable the moment it ships — never bolted on later. Three
requirements are non-negotiable for each feature build:
- **Structured log tracing.** Each run MUST generate a single run/correlation id that is
  threaded through every log line the run emits, so one run's activity can be isolated end
  to end. Every LLM call and every external/network call (discovery sources, the LLM
  provider) MUST be traced with at least its start, outcome (success/failure), duration, and
  source/endpoint identity. Traces MUST record call *metadata only* — never the resume text,
  `prefs.yaml`, profile, or any personal payload (Principle I); logging that content is a
  privacy violation, not observability.
- **Log rotation.** Logs MUST be written to a tailable file under the app data directory and
  MUST rotate by size or time (e.g. stdlib `logging.handlers.RotatingFileHandler`) with a
  bounded backup count, so log volume can never grow the local footprint without limit.
- **Monitoring / health signals.** Each feature MUST emit machine-visible health and error
  signals: a per-run summary (counts processed, new vs. seen, per-source failures) logged at
  run end, and errors surfaced via ntfy so a failure in an unattended run is noticed. A single
  dead discovery source MUST be logged and traced, then skipped — consistent with the
  Resilience constraint — never silently swallowed.
Observability MUST honor Principles II and VI: v1 uses stdlib logging with a rotating file
handler and ntfy — no hosted observability service, no metered cost, no agent framework. A
richer local trace viewer (e.g. Phoenix) MAY be used as an opt-in developer aid but MUST NOT
become a runtime dependency of the pipeline.
**Rationale:** This is an unattended monitor the user will trust with their job search; a
run they cannot see into is one they cannot debug or believe. A correlation id makes a run's
story reconstructable, call tracing makes the bounded LLM/network usage (Principles I–II)
auditable, rotation keeps a local-first tool from filling the disk, and ntfy-on-error means a
silent failure doesn't quietly stop surfacing roles.

## Technology & Operational Constraints

- **Stack:** Python 3.11+, FastAPI, SQLite, httpx, pypdf, NumPy, Claude Code CLI
  (`claude -p`, via Claude Pro subscription login; resume structuring + optional
  re-rank in MVP), Ollama (`mxbai-embed-large` for embeddings always; `Qwen2.5` as the
  local-LLM fast-follow target for structuring/re-rank), ntfy, running on the user's
  local machine (macOS). Substitutions MUST be justified against Principles I, II, and
  VI.
- **Single source of truth:** SQLite holds jobs, scores + breakdown, per-job state, and
  timestamps. State transitions MUST go through the store.
- **Filter before score:** Cheap hard-filter gates (location, work mode, company type,
  comp/seniority floors) MUST run before any embedding or LLM work, so cost stays
  proportional to relevant volume.
- **Resilience:** Discovery sources MUST be isolated with per-source try/except; a single
  dead source MUST NOT fail the run. Partial results are valid results.
- **Scheduling:** v1 runs are triggered manually via CLI; there is no always-on scheduler.
  Automatic scheduling (macOS `launchd`, preferred over cron for logging/retry) is an
  explicit fast-follow once the manually-triggered spine is proven. Whichever mechanism is
  in place, failures MUST be observable (logged to a file the user can tail, surfaced via
  ntfy on error).

## Development Workflow & Quality Gates

- **Constitution Check:** Every plan (`/speckit-plan`) MUST pass a Constitution Check gate.
  Any violation MUST be documented and justified in the plan's Complexity Tracking section
  or the design MUST be revised to comply.
- **Scope discipline:** Features listed as "Out of v1" in the HLD (resume tailoring,
  interview-prep handoff, company-research agent, implicit weight learning, ATS hardening)
  MUST NOT be pulled into v1 without an explicit amendment to scope.
- **Privacy review:** Any change touching the resume, profile, `prefs.yaml`, or an external
  network call MUST be reviewed against Principle I before merge.
- **Explainability review:** Any change to the scorer MUST keep the persisted score
  breakdown complete and the "why-matched" surface accurate.
- **Test-first gate:** No task implementing new behavior may be marked complete without
  a preceding test that was observed to fail, per Principle VII. Tasks/PRs MUST NOT
  mark tests as optional or defer them to a later cleanup pass.
- **Observability gate:** Every feature MUST ship with the observability required by
  Principle VIII — run-id-threaded structured logs, tracing of its LLM/external calls
  (metadata only), rotating log output, and an error/health signal (ntfy on failure).
  A feature that adds an LLM or network call or a new run stage MUST NOT be marked
  complete while that call/stage is untraced.

## Governance

This constitution supersedes other practices where they conflict. Amendments MUST be made
by editing this file, MUST state their rationale, and MUST bump the version per the policy
below. Dependent templates (`plan-template.md`, `spec-template.md`, `tasks-template.md`)
MUST be reviewed for alignment whenever a principle is added, removed, or materially
changed.

**Versioning policy (semantic):**
- **MAJOR** — backward-incompatible governance changes or removal/redefinition of a principle.
- **MINOR** — a new principle or section, or materially expanded guidance.
- **PATCH** — clarifications, wording, and non-semantic refinements.

**Compliance:** All plans and reviews MUST verify compliance with these principles.
Complexity that violates Principle VI MUST be explicitly justified or removed.

**Version**: 2.3.0 | **Ratified**: 2026-07-13 | **Last Amended**: 2026-07-13
