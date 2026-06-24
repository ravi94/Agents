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

## Project layout

See `PLAN.md` for the full design rationale.

```
src/web_researcher/
  agent.py        ReAct agent (LangGraph prebuilt)
  cli.py          Typer + Rich frontend
  config.py       pydantic-settings
  prompts.py      System prompt
  report.py       Markdown report writer
  tools/
    search.py     SearXNG client
    fetch.py     httpx + trafilatura
    summarize.py  Focused-summary tool (smaller model)
```

## Troubleshooting

- **`SearXNG did not return JSON`** — your SearXNG instance doesn't have `json` in `search.formats`. Add it and restart.
- **Agent loops forever / hits recursion limit** — lower `MAX_ITERATIONS` or try a stronger model. Small models (≤7B) often struggle with structured tool calls.
- **`Could not extract main content`** — page is JavaScript-rendered. v1 doesn't handle these; v2 could add a headless-browser fetch tool.
