# Portfolio News Agent — Design

A scheduled **tool-calling agent**. On each run it loads your holdings, lets a local
LLM decide what to research (via `web_search` / `web_fetch`), loops until the model
stops calling tools, then emails you a synthesized news brief.

Reference: `Tool-Calling Agent Architecture Design Diagram _ Claude.pdf` (Design 2).

> Status: **implemented**. This document describes the system as built. Run steps live
> in [README.md](README.md).

## Stack

- **Language:** Python 3.11+ (uses `X | None` hints; works on 3.9 via `from __future__ import annotations`)
- **LLM:** Qwen 3 (e.g. `qwen3:27b`), served locally via **Ollama** (OpenAI-compatible `/v1/chat/completions`)
- **Search:** pluggable — DuckDuckGo HTML (default, no key) or SerpAPI (key-gated)
- **Delivery:** Email (SMTP, multipart HTML+text)
- **Scheduler:** `launchd` (macOS) or cron
- **Dependencies:** `requests`, `pyyaml`, `python-dotenv`, `beautifulsoup4`, `trafilatura`, `lxml_html_clean`

## Architecture (flow)

```
Scheduler (launchd/cron)
        │ fires: python -m portfolio_news_agent.run
        ▼
┌─ agent loop ───────────────────────────────┐
│  Holdings + prompt ──► LLM (Qwen via Ollama)│
│                          │  tool_call       │
│                          ▼                  │
│                     tools: web_search,      │
│                            web_fetch        │
│                          │  result          │
│                          └──► back to LLM   │
│   (repeat until no more tool_calls, or a    │
│    guardrail forces the final summary)      │
└──────────────┬──────────────────────────────┘
               │ final brief (prose)
               ▼
     render HTML + plaintext
               │
               ▼
     Email delivery  (or --dry-run → stdout)
```

The model decides **what** to search and **how deep** to go — the loop is driven by
the model's tool calls, not a fixed pipeline.

## Components & responsibilities

| Module | Responsibility |
|---|---|
| `config.py` | Load env/`.env` + `holdings.yaml`; validate; expose a typed `Config` + `Holding` |
| `prompts.py` | System prompt (analyst role, news-only) + holdings context block |
| `llm_client.py` | Wrap Ollama chat API; send messages + tool schemas; parse tool calls (native + prompt fallback) |
| `tools/registry.py` | Tool JSON schemas sent each turn; `ToolDispatcher` that executes calls (URL dedupe, never raises) |
| `tools/web_fetch.py` | GET a URL → cleaned main text (trafilatura), truncated to a char budget |
| `tools/search/` | Pluggable `web_search`: common interface + `duckduckgo` and `serpapi` providers |
| `agent_loop.py` | Orchestrate: build prompt → call LLM → dispatch tools → feed results back → stop on no tool_calls; enforce guardrails |
| `brief.py` | Render the final prose brief to HTML (linkified) + plaintext; build the subject |
| `deliver/email.py` | Send the brief via SMTP as multipart HTML+text |
| `run.py` | Entry point the scheduler calls; `--dry-run`; logging; fail-fast email validation |

## Design details (as built)

### LLM client & tool-calling modes
POST to `{OLLAMA_BASE_URL}/chat/completions` with `model`, `messages`, `temperature`, and
(when applicable) `tools` + `tool_choice=auto`. Not every local build supports OpenAI-style
function calling, so the client supports three modes via `TOOL_MODE`:

- **`native`** — pass `tools`; read back `message.tool_calls`.
- **`prompt`** — omit `tools`; inject schemas into the system prompt and ask the model to emit
  a `{"tool_call": {"name", "arguments"}}` JSON object, parsed back into a `ToolCall`.
- **`auto`** (default) — try native; if the API returns no `tool_calls`, scan the content for a
  prompt-style JSON block. Safe default for an unknown Qwen build.

The agent loop is identical across modes — it only ever sees `ToolCall` objects.
Malformed JSON tool args are tolerated (logged, treated as empty args) rather than crashing.

### Tools
- **web_search** — one tool schema `{query, max_results}` → top N `{title, url, snippet}`,
  backed by a provider chosen at runtime by `SEARCH_PROVIDER`:
  - **`duckduckgo`** (default, no key): POST `https://html.duckduckgo.com/html/`, parse result
    anchors with `beautifulsoup4`, unwrap DDG redirect links. Best-effort — scraped endpoint.
  - **`serpapi`** (API key): GET SerpAPI Google endpoint; prefer `news_results`, fall back to
    `organic_results`. Higher reliability + news ranking. Requires `SERPAPI_API_KEY`.
  - Providers implement `search(query, max_results) -> list[SearchResult]` in `tools/search/`.
    Adding Tavily/Brave later is a new provider file + one line in `get_provider` — no loop changes.
- **web_fetch** — GET the URL, extract main article text with trafilatura, truncate to
  `FETCH_CHAR_BUDGET` chars. Fetched URLs are deduped within a run.

### Agent loop & guardrails
- System prompt: portfolio research analyst; goal = today's **material** news per holding;
  instructed to use tools and stop once it has enough.
- Loop: append assistant msg → if `tool_calls`, execute each and append `tool`-role results,
  continue; else treat content as the final brief.
- Guardrails: **`MAX_ITERATIONS`** (default 8), **`MAX_TOOL_CALLS`** (default 20), per-run
  wall-clock **`RUN_TIMEOUT_SECONDS`** (default 300), and fetched-URL dedupe. When a cap is hit,
  the loop asks the model to write the final brief from what it has (forced summary).

### Brief formatting
The model returns the brief as prose. `brief.py` escapes it, linkifies URLs, splits on blank
lines into paragraphs, and wraps it in a minimal HTML email; a plaintext alternative is kept
as the multipart fallback. Subject: `Portfolio Brief — {YYYY-MM-DD}`.

### Email delivery
SMTP with STARTTLS; multipart HTML+text. Creds from env (Gmail app password works), never
committed. `run.py` validates required email config up front (skipped under `--dry-run`).

### Observability & safety
- Structured INFO logging per turn (iteration, tool name + args, result sizes) to stderr.
- `--dry-run` prints the brief to stdout instead of emailing.
- Non-zero exit code on hard failure (scheduler-friendly).
- `test_smoke.py` mocks the LLM + tools to verify wiring (both tool modes, the loop, the
  guardrail cap, brief rendering, dry-run) without Ollama or network.

## Configuration (env / `.env`)

| Key | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama OpenAI-compatible endpoint |
| `MODEL_NAME` | `qwen3:27b` | Served model id |
| `TOOL_MODE` | `auto` | `native` \| `prompt` \| `auto` |
| `SEARCH_PROVIDER` | `duckduckgo` | `duckduckgo` \| `serpapi` |
| `SERPAPI_API_KEY` | — | Required when `SEARCH_PROVIDER=serpapi` |
| `MAX_ITERATIONS` | `8` | Max LLM turns per run |
| `MAX_TOOL_CALLS` | `20` | Max total tool calls per run |
| `RUN_TIMEOUT_SECONDS` | `300` | Wall-clock budget per run |
| `FETCH_CHAR_BUDGET` | `8000` | Max chars of article text fed back per fetch |
| `SMTP_HOST` / `SMTP_PORT` | `smtp.gmail.com` / `587` | SMTP server |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | — | SMTP auth (Gmail app password) |
| `EMAIL_FROM` / `EMAIL_TO` | — | Sender / recipient |

Holdings live in `holdings.yaml`: a list of `{ticker, name, optional notes}`.

## Project layout

```
portfolio_news_agent/
  config.py        env + holdings.yaml loading & validation
  prompts.py       system prompt + holdings context block
  llm_client.py    Ollama chat wrapper; native + prompt tool-calling
  agent_loop.py    the tool-calling loop + guardrails
  brief.py         final prose -> HTML + plaintext
  run.py           entry point (--dry-run, logging)
  tools/
    registry.py    tool schemas + dispatcher (URL dedupe)
    web_fetch.py   GET + trafilatura extraction
    search/
      __init__.py  SearchProvider interface + get_provider()
      duckduckgo.py
      serpapi.py
  deliver/
    email.py       SMTP multipart send
deploy/com.portfolio.newsagent.plist   launchd job (daily pre-market)
test_smoke.py      mocked end-to-end smoke tests
requirements.txt · .env.example · holdings.yaml · .gitignore · README.md
```

## Decisions (resolved)
- **Search backend:** pluggable. Ship **DuckDuckGo HTML (default, no key)** and **SerpAPI (key-gated)**, selectable via `SEARCH_PROVIDER`. Tavily/Brave deferred — droppable in later as new provider files.
- **Tool calling:** support **native + prompt** modes with **`auto`** default, since the served Qwen build's function-calling support is uncertain.
- **Schedule:** **daily pre-market** (every day, before market open; plist set to 07:00 local).
- **Brief scope:** **news only** — material news headlines + 1–2 line takeaways per holding. Price moves / analyst actions deferred to a later version.
- **Brief layout:** per-holding sections in one email.

## Out of scope (v1)
- Telegram/Discord delivery (diagram lists them; deferred).
- OpenClaw loop delegation (diagram option; deferred).
- Persistent history / dedupe across runs.
- Price moves / analyst actions in the brief (scope decision above).

## Possible next steps
- First real run against live Ollama to confirm the Qwen build's tool-calling mode (`native` vs `prompt`).
- Context-length trimming if long runs approach the model's window.
- Retry/backoff on transient search/fetch failures.
