# Quickstart & Validation: Resume Profile & Preferences Foundation

End-to-end validation that M1 works. Proves each user story independently. Details live in [contracts/cli.md](./contracts/cli.md) and [data-model.md](./data-model.md).

## Prerequisites

- Python 3.11+
- Claude Code CLI installed and logged in with a Pro/Max subscription (`claude` on PATH; verify `claude -p "say ok" --output-format json` returns JSON). No Anthropic API key needed.
- Project installed in a virtualenv: `pip install -e .` from repo root (installs `jobhunter` CLI + `pytest`).
- Optional: set `JOBHUNTER_HOME=./.tmp-jobhunter` to keep test state out of `~/.job-hunter/`.

## Run the test suite first (TDD gate)

Per Constitution VII, tests are written first and observed to fail, then pass. Validate the suite is green before manual checks:

```bash
pytest -q
```

Expect: unit tests (prefs validation, profile model, store schema, resume extraction) and integration tests (resume parser via fixture provider, prefs interview, db round-trip) all pass. LLM-touching tests use the `claude_profile_response.json` fixture — no live model call.

## Story 1 — Resume → persisted profile (P1)

```bash
jobhunter profile ./tests/fixtures/sample_resume.pdf
```

**Expect**: a summary (skills count, seniority, roles) and `profile.json` written under `JOBHUNTER_HOME`. Re-running any later command does **not** require the resume again (SC-002).

Validate replacement and failure handling:

```bash
jobhunter profile ./some_other_resume.pdf     # supersedes previous profile (FR-004)
jobhunter profile ./tests/fixtures/scanned_image.pdf   # image-only
```

**Expect** for the image-only case: a clear error, no LLM call, `profile.json` unchanged (FR-012).

## Story 2 — Preferences via guided interview + hand-edit (P2)

```bash
jobhunter prefs init          # one-time guided interview -> prefs.yaml
```

**Expect**: `prefs.yaml` created in the [documented shape](./contracts/prefs.schema.md), completable in under 5 minutes (SC-003).

Validate hand-edit is honored and interview isn't re-triggered:

```bash
# edit comp_floor_lpa in prefs.yaml by hand, then:
jobhunter prefs validate      # passes; no interview re-run (FR-007)
jobhunter prefs init          # refuses (prefs exists) unless --force (FR-008)
```

Validate error messaging on a bad edit:

```bash
# set work_modes: [remote, telepathic] then:
jobhunter prefs validate
```

**Expect**: non-zero exit naming `work_modes` / `telepathic` as invalid (FR-013, SC-006). Also confirm a `soft_weights` sum of e.g. 0.9 yields a **warning**, not an error (FR-008).

## Story 3 — Durable job store (P3)

```bash
jobhunter db init             # creates jobs.db if absent
jobhunter db init             # idempotent: existing store reused, not wiped (FR-011)
```

**Expect**: `jobs.db` with the `jobs` table and `PRAGMA user_version` set. The `test_db_roundtrip` integration test proves a written record reads back unchanged with `state` defaulting to `new` and timestamps populated (US3 scenario 3).

## Success criteria mapping

| Criterion | Validated by |
|---|---|
| SC-001 single-submission profile | Story 1 first command |
| SC-002 profile reused, 0 resubmissions | Story 1 re-run |
| SC-003 interview < 5 min | Story 2 `prefs init` |
| SC-004 hand-edits honored, no re-interview | Story 2 validate + init-refusal |
| SC-005 store zero data loss across runs | Story 3 idempotent re-init + round-trip test |
| SC-006 specific, log-free error messages | Story 1 image-only + Story 2 bad-edit |
