# job-hunter

Local resume/profile/preferences copilot foundation (**M1**). Turns a resume PDF
into a persisted structured profile, lets you own a hand-editable `prefs.yaml`,
and stands up a durable SQLite job store that later milestones will populate.

All state lives under a local app data directory — `~/.job-hunter/` by default,
or wherever `JOBHUNTER_HOME` points.

## Prerequisites

- **Python 3.11+** (the project requires `>=3.11`; a 3.9/3.10 venv will fail to install).
- **Claude CLI**, logged in — only needed for the `profile` command, which calls
  `claude -p` to structure the resume. Not required for `prefs` or `db`.

Check your Python:

```bash
python3.11 --version   # should print 3.11.x or newer
```

## Setup

From the repo root (`.../Agents/job-hunter`):

```bash
# 1. Create a virtual environment with Python 3.11+
python3.11 -m venv .venv

# 2. Install the package (editable) plus dev tools (pytest, ruff)
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

This installs the `jobhunter` console script into `.venv/bin/`.

## Running

```bash
# Top-level help
.venv/bin/jobhunter --help

# Subcommand help
.venv/bin/jobhunter profile --help
.venv/bin/jobhunter prefs --help
.venv/bin/jobhunter prefs init --help
.venv/bin/jobhunter db --help
```

Prefer typing just `jobhunter`? Activate the venv first:

```bash
source .venv/bin/activate
jobhunter --help
```

You can also run it as a module without the console script:

```bash
.venv/bin/python -m jobhunter.cli --help
```

### Commands (M1)

| Command | What it does | Status |
|---|---|---|
| `jobhunter profile <resume.pdf>` | Extract resume text → structure via Claude → write `profile.json`. | Skeleton (placeholder handler) — implemented in US1 |
| `jobhunter prefs init [--force]` | One-time guided interview → write `prefs.yaml`. Refuses to overwrite without `--force`. | Skeleton — implemented in US2 |
| `jobhunter prefs validate` | Validate `prefs.yaml` against the schema. | Skeleton — implemented in US2 |
| `jobhunter db init` | Create the SQLite job store (`jobs.db`) if absent; idempotent. | Skeleton — implemented in US3 |

> Placeholder commands currently print `not implemented yet` to stderr and exit
> non-zero. They become functional as their user stories land (see
> [tasks.md](specs/001-resume-profile-prefs/tasks.md)).

### App data location

All files resolve under the app data directory. Override it for testing or to
relocate your data:

```bash
JOBHUNTER_HOME=/tmp/jh-test .venv/bin/jobhunter db init
```

Resolved paths: `<home>/profile.json`, `<home>/prefs.yaml`, `<home>/jobs.db`.

## Development

```bash
# Run the test suite
.venv/bin/python -m pytest -q

# Lint
.venv/bin/ruff check src tests
```

Development is spec- and test-driven — see
[specs/001-resume-profile-prefs/](specs/001-resume-profile-prefs/) for the spec,
plan, and task list. Tests are written first and observed to fail before the
implementation lands (Constitution VII).

## Current status

Phase 2 (Foundational) complete: package installs, CLI dispatches, path
resolution works. Next up is **US1** — the `jobhunter profile` flow.
