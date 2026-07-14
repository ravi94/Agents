# job-hunter

Local job-search copilot. Turns a resume PDF into a persisted structured
profile (**M1**), lets you own a hand-editable `prefs.yaml` (**M1**), and now
discovers, normalizes, and dedups job postings from multiple sources into a
durable SQLite store, resiliently — a source outage never fails the run
(**M2**, complete).

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

### Commands

| Command | What it does | Status |
|---|---|---|
| `jobhunter profile <resume.pdf>` | Extract resume text → structure via Claude → write `profile.json`. | ✅ Implemented (US1) |
| `jobhunter prefs init [--force]` | One-time guided interview → write `prefs.yaml`. Refuses to overwrite without `--force`. | ✅ Implemented (US2) |
| `jobhunter prefs validate` | Validate `prefs.yaml` against the schema. | ✅ Implemented (US2) |
| `jobhunter db init` | Create the SQLite job store (`jobs.db`) if absent; idempotent. Prints the path and schema version. | ✅ Implemented (US3) |
| `jobhunter discover [--source NAME]... [--dry-run]` | Query job sources, normalize, dedup, and persist new postings into `jobs.db`. | ✅ Implemented (M2) |
| `jobhunter score [--dry-run]` | Hard-filter and composite-score every `state=new` job; persist `score`/`breakdown`/`matched_skills` or `filtered_out`+`reason`; alert once on high scorers. | ✅ Implemented (M3 US1–US3) |

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

#### Discovering jobs

`jobhunter discover` queries configured job sources, normalizes each posting,
dedups within the run and against the store, and persists genuinely new jobs
(`state=new`, `first_seen`/`last_seen` stamped, no scoring yet). Requires
`profile.json` and `prefs.yaml` to already exist:

Source credentials are read from a `.env` file (loaded automatically from the
current directory or a parent) or from real exported environment variables —
whichever is set wins, with exported variables taking precedence over `.env`:

```bash
cp .env.example .env
# then edit .env and fill in the keys you have
```

```bash
export JOBHUNTER_HOME="$(pwd)/data"
.venv/bin/jobhunter discover
# -> Discovery run <run-id> complete.
#      fetched: N   new: N   seen: N   skipped: N
#      sources:
#        jsearch  ok
#        adzuna   ok
```

- `--dry-run` — fetch, normalize, and dedup, but write nothing to the store (safe to inspect).
- `--source NAME` — restrict the run to one source (repeatable, e.g.
  `--source jsearch --source adzuna`). Default: all configured sources.
- A missing source credential (e.g. `JSEARCH_API_KEY`, or either
  `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`) skips that source and reports it as failed
  in the summary — it does **not** fail the run (exit code stays `0`). The
  same holds if a source errors mid-run (network failure, rate-limited after
  bounded retries): the run completes with the healthy sources' results and
  lists the failure per-source.
- The same role posted on both sources collapses into a single stored record
  (preferring whichever payload has more fields filled in), so running with
  both sources active doesn't double your job count.
- Responses are cached under `data/cache/` (~6h TTL by default) so same-day
  re-runs don't burn free-tier API quota.
- Implemented sources: **JSearch** (RapidAPI job search aggregator, needs
  `JSEARCH_API_KEY`) and **Adzuna** (India job search, needs `ADZUNA_APP_ID` +
  `ADZUNA_APP_KEY`).

**Getting a `JSEARCH_API_KEY`:**

1. Sign up / log in at [RapidAPI](https://rapidapi.com/).
2. Subscribe to the [JSearch API](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)
   — the **Basic** plan has a free monthly quota, enough for occasional manual
   `discover` runs.
3. On the API's "Endpoints" tab, copy the `X-RapidAPI-Key` value shown in the
   sample request headers (it's the same key across all RapidAPI APIs you're
   subscribed to).
4. Set `JSEARCH_API_KEY="<that value>"` in `.env` before running `jobhunter discover`.

**Getting `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`:**

1. Sign up / log in at the [Adzuna Developer portal](https://developer.adzuna.com/).
2. Register an app to get an `App ID` and `App Key` — the free tier's monthly
   call quota is enough for occasional manual `discover` runs.
3. Set `ADZUNA_APP_ID="<app id>"` and `ADZUNA_APP_KEY="<app key>"` in `.env`
   before running `jobhunter discover`.

Without these keys, `discover` still runs — it just reports the corresponding
source(s) as failed/unavailable in the summary and moves on (exit code `0`).

#### Scoring jobs

`jobhunter score` runs a hard-filter gate over every `state=new` job, then
computes a composite score (`comp`, `scope`, `stability`, `work_life_balance`)
against `prefs.yaml`'s soft weights and `profile.json`. Requires `profile.json`
and `prefs.yaml` to already exist (same preconditions as `discover`):

```bash
export JOBHUNTER_HOME="$(pwd)/data"
.venv/bin/jobhunter score
# -> Scoring run <run-id> complete.
#      filtered_out: N   scored: N   alerted: 0   reranked: 0
```

- `--dry-run` — compute filters/scores but write nothing to the store (safe to inspect).
- Jobs failing a hard filter (`locations`, `work_modes`, `company_types_allow`/
  `deny`, `comp_floor_lpa`, `seniority_floor`) become `state=filtered_out` with a
  `reason` naming every failed dimension; missing data for a dimension passes
  through rather than failing it.
- Surviving jobs become `state=scored` with a persisted `score` (`0.0`–`1.0`),
  a JSON `breakdown` (per-component value/weight/inferred), and a JSON
  `matched_skills` list — `score` and `breakdown` are always written together,
  never one without the other.
- The `scope` component uses a local [Ollama](https://ollama.com) embedding
  (`mxbai-embed-large`) to compare the job text against your profile's skills
  and roles. **No Ollama setup is required** — if the local endpoint is
  unreachable, `scope` transparently falls back to deterministic keyword
  overlap and the run still completes and persists scores. To use real
  embeddings instead:
  ```bash
  ollama pull mxbai-embed-large
  ollama serve
  ```
- Rerunning `score` only ever processes jobs currently `state=new` — already
  `filtered_out`/`scored` rows are left untouched, so reruns are idempotent.
- A newly-scored job at or above `prefs.yaml`'s `alerting.score_threshold`
  gets exactly one [ntfy](https://ntfy.sh) push, ever, up to
  `alerting.max_alerts_per_run` per run (same `JOBHUNTER_NTFY_TOPIC` topic as
  the error signal — see [Logs & monitoring](#logs--monitoring)). A job is
  never alerted twice, no matter how many times `score` reruns. With no topic
  configured, the run still completes and the `alerted` count is still
  reported — only the push itself is skipped.
- The optional `--rerank` qualitative pass is not yet wired — `reranked` in
  the summary stays `0` for now.

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
| HTTP response cache (`discover`) | `data/cache/` |

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
push notification, set an [ntfy](https://ntfy.sh) topic — leave it unset to
disable notifications. The same topic is used for two things: a whole-run
failure signal (M1/M2) and, since M3, a push on every job that clears your
`prefs.yaml` `alerting.score_threshold`:

```bash
export JOBHUNTER_NTFY_TOPIC="my-jobhunter-alerts"
```

ntfy topics on the public `ntfy.sh` server are just URL paths — anyone who
knows (or guesses) your topic name can read your notifications, so pick
something long and unpredictable (e.g. `jobhunter-a7f3c9d2`), not `alerts`.

To actually receive the push:

- **Browser** — open `https://ntfy.sh/<your-topic>` and leave the tab open
  (it uses server-sent events, no install needed).
- **Phone/desktop app** — install the [ntfy app](https://ntfy.sh/#subscribe),
  then subscribe to your topic name.
- **Self-hosted** — point `topic_env`/the ntfy base URL at your own server
  instead of `ntfy.sh` if you'd rather not use the public one (not wired up
  as a separate env var yet — edit `obs.py`'s `_post` if you need this now).

Subscribe *before* running `jobhunter score` or `discover`, since ntfy only
delivers to whoever's listening at send time (no offline queueing on the free
tier).

## Development

```bash
# Run the test suite
.venv/bin/python -m pytest -q

# Lint
.venv/bin/ruff check src tests
```

Development is spec- and test-driven — see
[specs/001-resume-profile-prefs/](specs/001-resume-profile-prefs/) (M1),
[specs/002-job-discovery-dedup/](specs/002-job-discovery-dedup/) (M2), and
[specs/003-job-scoring-filtering/](specs/003-job-scoring-filtering/) (M3) for the
specs, plans, and task lists. Tests are written first and observed to fail
before the implementation lands (Constitution VII).

## Current status

**M1 (US1, US2 & US3) complete. M2 (US1, US2 & US3 — single-source discovery, idempotent monitor, and Adzuna + multi-source resilience) complete.**

**M3 (job scoring, filtering & alerting) in progress — US1, US2 & US3 complete.**
The store is on schema v2 (`alerted_at`), the local Ollama embeddings client
is in, and `jobhunter score [--dry-run]` filters, composite-scores, and alerts
on every `state=new` job end-to-end (see [Scoring jobs](#scoring-jobs) above).
Only US4 (optional `--rerank` qualitative pass) is still to come.

See [CHANGELOG.md](CHANGELOG.md) for the full per-user-story history, and
[specs/](specs/) for the specs, plans, and task lists behind each milestone.
