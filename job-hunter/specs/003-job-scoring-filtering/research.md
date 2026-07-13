# Phase 0 Research: Job Scoring, Filtering & Alerting

All items below were resolved from the existing codebase (M1/M2 schemas and
seams) and the project constitution rather than left open — no
`NEEDS CLARIFICATION` markers remain.

## 1. Schema change: tracking "already alerted"

**Decision**: Add one nullable column, `alerted_at TEXT`, to the existing
`jobs` table; bump `SCHEMA_VERSION` from `1` to `2`. `init_db` checks
`PRAGMA table_info(jobs)` for the column's presence and runs
`ALTER TABLE jobs ADD COLUMN alerted_at TEXT` only if it is missing, before
stamping the new `PRAGMA user_version`.

**Rationale**: The `jobs` table already reserves `score`/`breakdown`/
`matched_skills`/`reason` for this milestone (M1's `store/db.py` comment says
so explicitly), but nothing tracks *whether a notification was already sent*.
Folding that into `state` would conflate "how far a job has progressed in
triage" (new → filtered_out/scored → user-set states in a later milestone)
with "was the user already pinged about it" — a job the user manually
resets or revisits must still never re-alert. A dedicated, independent
column keeps FR-009 (never re-alert) correct regardless of later state
changes, and a nullable-by-default `ADD COLUMN` is a safe, additive migration
that doesn't disturb existing M1/M2 rows.

**Alternatives considered**:
- *Reuse `state` (e.g. `"alerted"` as a state value)* — rejected: would block
  a job from also carrying a real triage state (e.g. "interested") at the
  same time, and would make "already alerted" ambiguous once triage states
  land in a later milestone.
- *A separate `alerts` table keyed by job id* — rejected as premature
  normalization (Constitution VI, YAGNI): one nullable column answers the one
  question this milestone needs ("has this job ever been alerted on?") with
  no joins required.

## 2. Composite scoring: deterministic rules + local embeddings

**Decision**: Each `SoftWeights` component is scored in `[0, 1]` and combined
into the overall score as a weighted sum using the weights already validated
in `prefs.yaml` (no renormalization, per M1's existing warning-only policy):

- **`comp`** — deterministic: the job's parsed salary (when present) is
  normalized against `hard_filters.comp_floor_lpa` (a ratio capped at 1.0);
  absent salary scores a neutral midpoint rather than zero (FR-003 —
  missing data must not be punished as if it were a hard failure).
- **`stability`** and **`work_life_balance`** — deterministic, company-type
  proxy lookups (the same `company_types_allow`/company-type signal already
  in `prefs.yaml`), explicitly labeled as *inferred* wherever they appear in
  the breakdown (FR-007, Constitution V).
- **`scope`** — semantic: cosine similarity between an embedding of the
  job's title+description and an embedding of the profile's skills+roles,
  computed via the **local Ollama `mxbai-embed-large` model** (Constitution I:
  "Embeddings MUST always run locally via Ollama... in both the MVP and
  fast-follow phases"). `matched_skills` is populated from the profile skills
  whose individual embeddings score above a similarity threshold against the
  job text — giving both a numeric component and an inspectable skill list
  from the same computation (FR-005/FR-006).

Ollama's REST API (`http://localhost:11434/api/embeddings`) is called via the
already-declared `httpx` dependency — no new HTTP client is needed. Vector
math (cosine similarity) uses **NumPy**, already named in the constitution's
stack but not yet a dependency of any prior milestone; it is added to
`pyproject.toml` here.

**Resilience**: if the local Ollama endpoint is unreachable or times out, the
run MUST NOT fail. The `scope` component falls back to a simple deterministic
keyword-overlap between profile skills and job text for that run only; the
fallback is traced (`obs.trace`) and logged so it's visible, never silent.

**Rationale**: Principle I commits to local embeddings for *any* semantic
matching, not as a someday-maybe — using them for the one component that
benefits from semantic (not exact-string) matching keeps that commitment
concrete in the first milestone that needs matching at all, while `comp`/
`stability`/`work_life_balance` stay plain deterministic Python per
Principle VI (no LLM/embedding call needed for a numeric threshold or a
lookup table).

**Alternatives considered**:
- *Pure keyword/substring overlap for all components, no embeddings at all*
  — rejected: leaves Principle I's embeddings commitment unfulfilled with no
  concrete plan to introduce it later, and produces weaker skill matching
  (misses paraphrases like "Node.js" vs "server-side JavaScript").
- *Route scope-matching through the LLM provider (Claude) instead of local
  embeddings* — rejected: Principle I is explicit that embeddings specifically
  must stay local/Ollama regardless of which provider is active for
  text-generation; Claude has no embeddings endpoint to swap to.

## 3. Optional LLM re-rank: extend the existing provider seam

**Decision**: Add one new abstract method to `LLMProvider`
(`llm/provider.py`): `rerank(candidates, profile) -> dict[str, str]`, mapping
job id → a short qualitative reason string, implemented for the MVP by
`ClaudeCLIProvider` as a single `claude -p` call carrying only the top ~25
survivors' title/description/matched-skills and the profile's skills/roles —
never `prefs.yaml` or any tracking state (Constitution I).

**Rationale**: Reuses the swap seam already established for resume
structuring rather than inventing a second provider hierarchy (Constitution
VI); "one bounded call regardless of survivor count" is enforced by the
orchestrator slicing to the top ~25 before calling, not by the provider.

**Alternatives considered**: A separate `RerankProvider` ABC — rejected as an
unnecessary second interface for the same underlying swap concern (provider
identity), when one interface with two methods says the same thing with less
surface.

## 4. CLI shape: re-rank is opt-in

**Decision**: `jobhunter score [--dry-run] [--rerank]`. Base scoring
(filter → score → alert) never calls an LLM; `--rerank` opts into the single
bounded Claude call for the top ~25 survivors.

**Rationale**: Keeps the default path fully local/deterministic and usable
without a Claude CLI login (mirrors `discover`/`db init`, which also need no
LLM), consistent with Principle II ("re-rank is... executed manually, not
continuously") — the user explicitly asks for the qualitative pass on the
runs where they want it.

**Alternatives considered**: Re-rank on by default — rejected: would make
every `score` invocation depend on Claude CLI login, which today only
`profile` requires, and would spend shared Pro-subscription quota (Principle
II) even on runs where the user just wants the mechanical ranking refreshed.

## 5. Alerting: generalize the existing ntfy helper

**Decision**: Rename/generalize `obs.notify_error`'s underlying POST helper
into a small internal `obs._post`-backed `notify(message)` used by both the
existing error path and a new alert path — no new notification channel,
config variable, or dependency.

**Rationale**: `obs.py` already owns the one ntfy integration point
(`JOBHUNTER_NTFY_TOPIC`, best-effort, never crashes the run); alerting on a
new high-scoring job is the same "push a local text message" operation as an
error signal, just with different content and trigger.

**Alternatives considered**: A separate alerting module with its own topic
env var — rejected: would fragment the single notification channel
Principle VIII already established, for no behavioral gain.
