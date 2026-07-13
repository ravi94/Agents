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
| `jobhunter profile <resume.pdf>` | Extract resume text → structure via Claude → write `profile.json`. | ✅ Implemented (US1) |
| `jobhunter prefs init [--force]` | One-time guided interview → write `prefs.yaml`. Refuses to overwrite without `--force`. | ✅ Implemented (US2) |
| `jobhunter prefs validate` | Validate `prefs.yaml` against the schema. | ✅ Implemented (US2) |
| `jobhunter db init` | Create the SQLite job store (`jobs.db`) if absent; idempotent. Prints the path and schema version. | ✅ Implemented (US3) |

#### Building your profile

`jobhunter profile` needs the Claude CLI logged in (it calls `claude -p` to
structure the resume). Point it at a text-based PDF:

```bash
export JOBHUNTER_HOME="$(pwd)/data"          # keep state inside the repo
.venv/bin/jobhunter profile path/to/resume.pdf
# -> writes data/profile.json and prints a skills / seniority / roles summary
```

The write is atomic and the resume text is the only thing sent to the provider.
An image-only/scanned PDF is rejected before any Claude call, and any failure
leaves an existing `profile.json` untouched.

#### Setting your preferences

`jobhunter prefs init` runs a one-time guided interview (no Claude CLI needed)
and writes `prefs.yaml` — your hard filters (locations, work modes, company
types, comp floor, seniority floor), soft weights, and alerting thresholds:

```bash
export JOBHUNTER_HOME="$(pwd)/data"
.venv/bin/jobhunter prefs init
# -> writes data/prefs.yaml, then reminds you it's yours to hand-edit
```

The file is meant to be hand-edited afterward — the interview never re-runs or
overwrites it unless you pass `--force`. Validate your edits any time:

```bash
.venv/bin/jobhunter prefs validate
```

`validate` exits `0` when the file is valid. A soft-weight sum that drifts from
`~1.0` prints a **warning** but still passes (your values are preserved, never
silently renormalized). Any invalid value exits non-zero with a message naming
the offending field, so you can fix it without reading logs.

### App data location

All state resolves under the app data directory. The default is `~/.job-hunter/`,
but this project ships a `data/` folder and uses it as the home via the
`JOBHUNTER_HOME` override, so all files stay inside the repo:

```bash
export JOBHUNTER_HOME="$(pwd)/data"   # run from the repo root
.venv/bin/jobhunter db init            # -> ./data/jobs.db
```

Put the `export` in your shell session (or prefix individual commands with
`JOBHUNTER_HOME="$(pwd)/data"`) so the CLI reads/writes under `data/`.

Resolved paths (with the override above):

| File | Location |
|---|---|
| Profile | `data/profile.json` |
| Preferences | `data/prefs.yaml` |
| Job store | `data/jobs.db` |

The `data/` folder is tracked in git but its **contents are gitignored** — your
profile, prefs, and DB stay local. Set `JOBHUNTER_HOME` to any other path to
relocate the data.

### Logs & monitoring

Every run writes a structured, rotating log under the app data directory, with a
per-run correlation id threaded through each line and every LLM/external call
traced (metadata only — never your resume or prefs content):

```bash
tail -f "$JOBHUNTER_HOME/logs/jobhunter.log"   # or ~/.job-hunter/logs/jobhunter.log
```

The file rotates by size (bounded backups) so it never grows unbounded. To get a
push notification when a run fails, set an [ntfy](https://ntfy.sh) topic — leave
it unset to disable notifications:

```bash
export JOBHUNTER_NTFY_TOPIC="my-jobhunter-alerts"
```

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

**US1, US2 & US3 complete — M1 stories all landed.**

- **US1** — `jobhunter profile <resume.pdf>` turns a resume into a validated,
  atomically persisted `profile.json` (extract → structure via Claude → write).
- **US2** — `jobhunter prefs init` seeds a hand-editable `prefs.yaml` via a
  guided interview; `jobhunter prefs validate` checks it (field-named errors,
  weight-sum warnings).
- **US3** — `jobhunter db init` creates the durable SQLite job store
  (`jobs.db`) idempotently, with the full `jobs` schema (`user_version`) that
  later milestones (discovery, scoring, triage) populate.
