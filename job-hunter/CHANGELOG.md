# Changelog

All notable changes to job-hunter are documented here, grouped by milestone/user
story. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### M2 — job discovery, normalization & dedup (see [specs/002-job-discovery-dedup/](specs/002-job-discovery-dedup/))

- **US1 (MVP)** — Added `jobhunter discover`: fetches from JSearch, normalizes
  each posting into the canonical `Job` shape, classifies work mode, dedups
  within the run, and persists genuinely new jobs (`state=new`) into `jobs.db`.
- **US2** — Made repeated `discover` runs idempotent: already-seen jobs only
  advance `last_seen` (never re-added, never reset off a later `state` like
  `interested`); the run summary distinguishes `new` vs `seen` counts.
- **US3** (Adzuna + multi-source resilience) — not yet implemented.

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
