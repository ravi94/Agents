# CLAUDE.md

Guidance for Claude when working in this repo.

## What this is

A local-first CLI research agent. **Ollama** does the reasoning, **SearXNG** does the search, **LangGraph**'s prebuilt ReAct agent (`create_react_agent`) glues them together. One-shot per invocation: question in, streamed thinking + markdown report out.

Entry point: `research "..."` (script in `pyproject.toml`) or `python -m web_researcher "..."`.

## Stack

Python ≥3.11. LangGraph + `langchain-ollama`, `httpx`, `trafilatura` (article extraction), `typer` + `rich` (CLI), `pydantic-settings` (config), `pytest` + `respx` (HTTP mocking) for tests. Optional observability via `arize-phoenix` + `openinference-instrumentation-langchain` + OTel SDK — opt-in only.

## Layout

```
src/web_researcher/
  config.py       Settings (pydantic-settings, reads .env). searxng_url is required.
  agent.py        build_agent() — wires ChatOllama + 3 tools into create_react_agent
  prompts.py      SYSTEM_PROMPT — enforces [n] citations + Sources list, no fabricated URLs
  cli.py          Typer entrypoint; streams agent events via stream_mode="values"
  report.py       save_report() — writes reports/YYYY-MM-DD_HHMMSS_slug.md with frontmatter
  tracing.py      init_tracing() — opt-in embedded Phoenix + OTel + LangChain instrumentation. Lazy imports.
  __main__.py     `python -m web_researcher` shim
  tools/
    __init__.py   Lazy __getattr__ exports (so tests don't force-load Ollama)
    search.py     SearXNG /search?format=json → dedupe + denylist filter
    fetch.py     httpx GET + trafilatura.extract → cleaned main text, truncated to max_page_chars
    summarize.py  Secondary ChatOllama call (smaller summarizer model) for focused compression
tests/            pytest + respx, no live network
```

`PLAN.md` has the original design rationale and locked decisions — read it before suggesting architectural changes.

## Conventions

- Tools are built by `make_*_tool(settings)` factories returning a `StructuredTool` — they close over `Settings` rather than reading env at call time. Keep this pattern.
- Tool return values are **JSON strings** (the ReAct loop reads them back as observations). Errors are returned as `{"error": "..."}`, never raised — the agent decides what to do.
- `tools/__init__.py` uses lazy `__getattr__` imports on purpose: importing `search` for a test must not load `langchain_ollama`. Don't replace with eager imports.
- Settings are immutable-by-convention: CLI overrides (`--model`, `--max-iterations`) mutate the `Settings` instance in `cli.py` before `build_agent`. New overrides should follow that shape.
- Config has no `searxng_url` default — misconfiguration should fail loudly at startup.

## Running

```bash
uv sync                    # creates .venv + installs deps (incl. dev group)
cp .env.example .env       # set SEARXNG_URL at minimum
uv run pytest              # all tests are offline (respx-mocked)
uv run research "your question"
uv run research "your question" --trace    # opens Phoenix UI at http://127.0.0.1:6006
```

Dependency management is **uv**. Use `uv add <pkg>` / `uv add --dev <pkg>` to change deps (updates `pyproject.toml` + `uv.lock`); don't hand-edit and `pip install`. Dev deps live in `[dependency-groups]`, not `[project.optional-dependencies]`.

Requires Ollama running locally with `qwen2.5:14b` and `llama3.1:8b` pulled, and a SearXNG instance with `json` in `search.formats`.

## Gotchas

- **SearXNG must have `json` in `search.formats`** in its `settings.yml`, or every search returns the "did not return JSON" error.
- **trafilatura returns `None` on JS-rendered pages.** The fetch tool surfaces this as an error; v1 won't fix it (a headless-browser tool is the v2 path noted in PLAN §9).
- **Small Ollama models (<7B) hallucinate tool args.** Keep temperature low (0.2 base, 0.1 summarizer) and lean on the strict pydantic schemas on tool inputs.
- **Recursion limit is `max_iterations * 2 + 5`** in `cli.py` — each ReAct step is roughly two graph nodes (LLM + tool), so the multiplier matters.
- **`reports/` is gitignored.** Don't commit generated reports.
- **Tracing is opt-in.** `TRACING_ENABLED=false` by default. Turn on with `--trace` or `TRACING_ENABLED=true`. Phoenix UI auto-launches in-process at `http://127.0.0.1:6006`; OTel/Phoenix imports are deferred inside `tracing.init_tracing` so a normal run has zero observability overhead. `LangChainInstrumentor` covers the whole graph (ChatOllama + every `StructuredTool`) — don't add per-component instrumentation.

## Testing

`uv run pytest` runs offline — `respx` mocks all HTTP. There is no live-network integration test by design. When adding a tool, add a `respx`-mocked unit test mirroring `test_search.py` / `test_fetch.py`.
