# Changelog

All notable changes to job-hunter are documented here, grouped by milestone/user
story. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### M3 — job scoring, filtering & alerting (complete; see [specs/003-job-scoring-filtering/](specs/003-job-scoring-filtering/))

- **Schema v2** — Bumped the `jobs` store to schema version 2, adding the
  write-once `alerted_at` column. Existing v1 stores are migrated in place via
  `ALTER TABLE` on `init` — no rows are disturbed.
- Added a local embeddings client (Ollama `mxbai-embed-large`, used for the
  `scope` score component) that returns `None` on any failure instead of
  raising, so callers get a clean fallback signal — never a live-call
  dependency.
- **US1 (MVP, complete)** — Landed the scoring engine: the hard-filter gate
  (`prefs.yaml` locations / work modes / company types / comp floor / seniority
  floor, with missing data treated as pass-through), the composite scorer
  (`comp`/`stability`/`work_life_balance`/`scope` components + matched skills,
  with a keyword-overlap fallback when embeddings are unavailable), and the
  `filter → score → persist` orchestrator (filtered jobs → `state=filtered_out`
  with a reason; survivors → `state=scored` with `score`/`breakdown`/
  `matched_skills` written atomically; `dry_run` reports counts but writes
  nothing). Wired up as `jobhunter score [--dry-run]`, printing the
  `filtered_out`/`scored`/`alerted`/`reranked` run summary; the embeddings call
  is traced (metadata only) with the keyword-overlap fallback logged, and a
  whole-run failure fires the existing ntfy error signal.
- **US2 (complete)** — Hardened explainability: `score` and `breakdown` are
  always written together (never one without the other), and the CLI summary
  now surfaces the top-scoring job's title plus its top contributing factor
  (`format_breakdown`) without a separate query.
- **US3 (complete)** — Added threshold alerting: generalized `obs.notify_error`
  into a shared `obs.notify(message)`, added a write-once `mark_alerted`
  store seam, and wired an alert step into the orchestrator — a `state=scored`
  job at/above `alerting.score_threshold` with `alerted_at IS NULL` gets
  exactly one ntfy push, ever, up to `alerting.max_alerts_per_run` per run.
  Already-alerted jobs are never revisited, no matter how many times `score`
  reruns. `--dry-run` reports the count that *would* alert but sends nothing.
- **US4 (complete)** — Added the optional `--rerank` qualitative pass: extended
  the `LLMProvider` seam with `rerank(candidates, profile) -> dict[str, str]`,
  implemented by `ClaudeCLIProvider` as a single `claude -p` call; the new
  `scoring/rerank.py` orchestrator bounds this run's scored survivors to the
  top ~25 by `score`, redacts each candidate to `id`/`title`/`description`/
  `matched_skills` (never `prefs.yaml` or tracking state), calls the provider
  exactly once, and writes each returned reason back onto its job. A provider
  failure/timeout is caught and never affects already-persisted scores/alerts.
  Strictly opt-in — base scoring never constructs a provider or calls an LLM
  unless `--rerank` is passed.

### M2 — job discovery, normalization & dedup (see [specs/002-job-discovery-dedup/](specs/002-job-discovery-dedup/))

- **US1 (MVP)** — Added `jobhunter discover`: fetches from JSearch, normalizes
  each posting into the canonical `Job` shape, classifies work mode, dedups
  within the run, and persists genuinely new jobs (`state=new`) into `jobs.db`.
- **US2** — Made repeated `discover` runs idempotent: already-seen jobs only
  advance `last_seen` (never re-added, never reset off a later `state` like
  `interested`); the run summary distinguishes `new` vs `seen` counts.
- **US3** — Added the Adzuna India source, run alongside JSearch through the
  common `JobSource` interface with per-source failure isolation (one dead
  source never fails the run) and cross-source dedup (the same role posted on
  both sources collapses into a single stored record).
- Source credentials (`JSEARCH_API_KEY`, `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`) can
  now be supplied via a `.env` file (see `.env.example`), loaded automatically
  on every run; exported environment variables still take precedence.

## M1 — resume/profile/preferences foundation (see [specs/001-resume-profile-prefs/](specs/001-resume-profile-prefs/))

- **US1** — Added `jobhunter profile <resume.pdf>`: turns a resume into a
  validated, atomically persisted `profile.json` (extract → structure via
  Claude → write).
- **US2** — Added `jobhunter prefs init` to seed a hand-editable `prefs.yaml`
  via a guided interview; `jobhunter prefs validate` checks it (field-named
  errors, weight-sum warnings).
- **US3** — Added `jobhunter db init`: creates the durable SQLite job store
  (`jobs.db`) idempotently, with the full `jobs` schema (`user_version`) that
  later milestones (discovery, scoring, triage) populate.
