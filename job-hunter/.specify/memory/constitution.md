<!--
Sync Impact Report
Version change: 2.1.0 → 2.2.0
Rationale: Added a Test-First Development principle (non-negotiable TDD) at the
user's request. A new principle is a MINOR bump per this document's own versioning
policy. LLM-touching code (resume parser, re-rank) is explicitly scoped to testing
the surrounding plumbing (schema/contract validation, error handling, the
provider-swap interface) via mocked/fixture responses — never asserting on exact
LLM wording, since model output isn't deterministic.
Modified principles: none
Added sections:
  - VII. Test-First Development (NON-NEGOTIABLE)
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md ✅ reviewed — Testing line is a fill-in-at-plan-time
    placeholder already; no structural edit needed
  - .specify/templates/spec-template.md ✅ reviewed — no edit needed
  - .specify/templates/tasks-template.md ⚠ updated — removed "OPTIONAL — only if
    tests requested" framing on per-story test sections and the "(if requested)"
    qualifiers, since tests are now mandatory project-wide, not opt-in
Deferred TODOs: none
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

**Version**: 2.2.0 | **Ratified**: 2026-07-13 | **Last Amended**: 2026-07-13
