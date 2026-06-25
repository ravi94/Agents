# web-researcher

A local web research agent that uses **Ollama** for reasoning and **SearXNG** for search, wired together as a LangGraph ReAct agent. Runs from the CLI, streams its thinking live, saves a markdown report.

## Prerequisites

- **Ollama** running locally with the models pulled:
  ```bash
  ollama pull qwen2.5:14b
  ollama pull llama3.1:8b
  ```
- **SearXNG** running locally with the JSON format enabled. In your `settings.yml`:
  ```yaml
  search:
    formats:
      - html
      - json
  ```
- Python 3.11+.
- [uv](https://docs.astral.sh/uv/) for dependency management.

## Setup

```bash
cd web-researcher
uv sync   # creates .venv and installs deps (including the dev group)

cp .env.example .env
# edit .env — at minimum, set SEARXNG_URL to your instance
```

## Use

```bash
uv run research "What are the tradeoffs between Qdrant and Weaviate in 2026?"
```

Or:

```bash
uv run python -m web_researcher "your question here"
```

Options:

| Flag | Purpose |
|---|---|
| `--model / -m` | Override the base model for this run (e.g. `-m qwen2.5:7b`) |
| `--max-iterations` | Cap the ReAct loop (default 12) |
| `--output-dir / -o` | Where to save the report (default `reports/`) |
| `--no-save` | Don't write the markdown file, just print |
| `--trace` | Send traces to Phoenix for this run (see [Observability](#observability)) |

## What you'll see

The agent streams its tool calls and observations to the terminal:

```
─── Step 1  →  search_web(query='Qdrant vs Weaviate 2026') ───
search_web →
  1. Comparing Vector Databases in 2026  https://...
  2. Qdrant 1.10 Release Notes           https://...

─── Step 2  →  fetch_page(url='https://...') ───
fetch_page →
  Comparing Vector Databases in 2026
  ...
```

At the end, a rendered markdown report and the saved file path.

## Observability

Optional [Phoenix](https://arize.com/docs/phoenix) tracing shows the full ReAct
loop — every LLM call, tool invocation, prompt, token count, and latency — as a
span tree in a web UI. It's opt-in and off by default (`TRACING_ENABLED=false`).

**Recommended: standalone server (persists traces, UI stays up after the run).**

The CLI is one-shot — the process exits as soon as a run finishes. So run
Phoenix as a separate, long-lived server and point the agent at it. An embedded
in-process server (the default if no endpoint is set) uses an in-memory DB that
dies with the CLI process, taking its traces with it before you can view them.

```bash
# terminal 1 — leave running; uses a file-backed DB at ~/.phoenix/phoenix.db
uv run phoenix serve
```

In `.env`:

```bash
TRACING_ENABLED=true
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006
```

```bash
# terminal 2
uv run research "your question"
```

Open <http://localhost:6006> and select the **web-researcher** project. The
trace stays available after the command exits.

> `--trace` on the CLI just flips `TRACING_ENABLED` on for that run; it still
> reads `PHOENIX_COLLECTOR_ENDPOINT` from `.env`. With no endpoint set, it falls
> back to embedded mode (fine for notebooks / long-lived processes, not the CLI).

## Project layout

See `PLAN.md` for the full design rationale.

```
src/web_researcher/
  agent.py        ReAct agent (LangGraph prebuilt)
  cli.py          Typer + Rich frontend
  config.py       pydantic-settings
  prompts.py      System prompt
  report.py       Markdown report writer
  tracing.py      Opt-in Phoenix / OpenInference tracing
  tools/
    search.py     SearXNG client
    fetch.py     httpx + trafilatura
    summarize.py  Focused-summary tool (smaller model)
```

## Troubleshooting

- **`SearXNG did not return JSON`** — your SearXNG instance doesn't have `json` in `search.formats`. Add it and restart.
- **Agent loops forever / hits recursion limit** — lower `MAX_ITERATIONS` or try a stronger model. Small models (≤7B) often struggle with structured tool calls.
- **`Could not extract main content`** — page is JavaScript-rendered. v1 doesn't handle these; v2 could add a headless-browser fetch tool.
- **Phoenix UI is empty / `web-researcher` project never appears** — you're in embedded mode. The in-process server dies when the one-shot CLI exits, discarding its in-memory traces. Run a standalone `phoenix serve` and set `PHOENIX_COLLECTOR_ENDPOINT` (see [Observability](#observability)).
- **`RuntimeError: server took too long to start`** — embedded Phoenix has a hardcoded 5s startup limit; first launch can exceed it while creating its DB. Use the standalone server instead, or pre-warm once with `uv run python -c "import phoenix; phoenix.launch_app()"`.
