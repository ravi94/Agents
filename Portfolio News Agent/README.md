# Portfolio News Agent

A scheduled **tool-calling agent**. Each run loads your holdings, lets a local LLM
(Qwen via Ollama) decide what to research using `web_search` / `web_fetch`, loops until
the model stops calling tools, then emails you a synthesized news brief.

See [design.md](design.md) for architecture and decisions.

## Prerequisites

- **Python 3.11+** (works on 3.9+, but 3.11+ is recommended).
- **[Ollama](https://ollama.com)** installed and able to serve a tool-capable model.
- For email delivery: an SMTP account. For Gmail, create an **App Password**
  (Google Account → Security → 2-Step Verification → App passwords) and use that as
  `SMTP_PASSWORD` — your normal password will not work.
- For the default `searxng` search backend: a locally-hosted SearXNG instance
  (no API key). See [`../../mcp/web_search`](../../mcp/web_search) for a ready-to-run
  Docker setup; point `SEARXNG_URL` at it (default `http://localhost:8080`).
- For `serpapi` search (optional): a [SerpAPI](https://serpapi.com) API key.

## Setup

```bash
# 1. From the project root, create a virtualenv and install dependencies.
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Create your config and fill it in (SMTP creds, optionally SERPAPI_API_KEY).
cp .env.example .env
$EDITOR .env

# 3. List your holdings.
$EDITOR holdings.yaml       # list of {ticker, name, optional notes}
```

Start Ollama and pull the model named in `.env` (`MODEL_NAME`):

```bash
ollama serve            # in a separate terminal, if not already running
ollama pull qwen3:27b   # must match MODEL_NAME in .env
```

## Run

Recommended first run — verify end to end without sending email:

```bash
.venv/bin/python -m portfolio_news_agent.run --dry-run
```

This prints the brief to the terminal. The INFO logs (on stderr) show which tool mode
fired and each search/fetch — useful for confirming your Qwen build's tool calling.
If tools never fire, set `TOOL_MODE=prompt` in `.env` (see below).

Once the dry run looks right, send for real:

```bash
.venv/bin/python -m portfolio_news_agent.run
```

Exit code is non-zero on hard failure (good for schedulers). Logs go to stderr.

To save the brief to a file instead of emailing it, set `DELIVERY_MODE=file` in
`.env`. Each run writes `summary-<date>.md` (e.g. `summary-2026-06-19.md`) to
`OUTPUT_DIR` (defaults to the project root). No SMTP config is required in this mode.

## Configuration (`.env`)

| Key | Purpose |
|---|---|
| `OLLAMA_BASE_URL` | Ollama OpenAI-compatible endpoint (default `http://localhost:11434/v1`) |
| `MODEL_NAME` | Served model id (e.g. `qwen3:27b`) |
| `TOOL_MODE` | `auto` (default), `native`, or `prompt` — see below |
| `SEARCH_PROVIDER` | `searxng` (default, local, no key) or `serpapi` |
| `SEARXNG_URL` | SearXNG base URL (default `http://localhost:8080`) |
| `SEARXNG_RATE_LIMIT_RPS` / `_BURST` | Token-bucket throttle (default `1.0` / `3`) |
| `SEARXNG_MAX_RETRIES` / `_BACKOFF_BASE` / `_BACKOFF_MAX` | Retry/backoff on 429/5xx |
| `SEARXNG_TIMEOUT` | Per-request timeout in seconds (default `15`) |
| `SERPAPI_API_KEY` | Required only when `SEARCH_PROVIDER=serpapi` |
| `MAX_ITERATIONS` / `MAX_TOOL_CALLS` / `RUN_TIMEOUT_SECONDS` | Loop guardrails |
| `FETCH_CHAR_BUDGET` | Max chars of article text fed back per fetch |
| `DELIVERY_MODE` | `email` (default, SMTP) or `file` (write `summary-<date>.md`) |
| `OUTPUT_DIR` | Where to write the summary file when `DELIVERY_MODE=file` (default: project root) |
| `SMTP_*`, `EMAIL_FROM`, `EMAIL_TO` | Email delivery (Gmail app password works) |

### Switching search backends

The agent always sees one `web_search` tool; the backend is chosen by `SEARCH_PROVIDER`.
- **`searxng`** (default) — no key, queries a locally-hosted SearXNG JSON API (the
  same instance the [`web_search` MCP](../../mcp/web_search) uses). Includes the MCP's
  throttle protection: token-bucket request spacing + exponential backoff/retry on
  429/5xx (see [`tools/search/_throttle.py`](portfolio_news_agent/tools/search/_throttle.py)).
  Requires a running SearXNG container.
- **`serpapi`** — Google results via API key; more reliable + better news ranking.

Adding Tavily/Brave later is just a new provider file under
[portfolio_news_agent/tools/search/](portfolio_news_agent/tools/search/) plus one line in
`get_provider` — no changes to the agent loop.

### Tool calling (`TOOL_MODE`)

Not every local model build supports OpenAI-style function calling. The client handles both:
- **`native`** — passes `tools` to the API and reads back `message.tool_calls`.
- **`prompt`** — injects the tool schemas into the system prompt and asks the model to emit
  a `{"tool_call": {...}}` JSON object, which the client parses back into a tool call.
- **`auto`** (default) — tries native, and if the API returns no `tool_calls`, scans the
  content for a prompt-style JSON block. Safe default for an unknown Qwen build.

The agent loop is identical in all modes. If your Qwen build doesn't do native tool calls,
set `TOOL_MODE=prompt`.

## Tests

No live Ollama or network needed — the LLM and tools are mocked:

```bash
.venv/bin/python test_smoke.py
```

## Scheduling

### launchd (macOS) — daily pre-market

Edit the absolute paths in [deploy/com.portfolio.newsagent.plist](deploy/com.portfolio.newsagent.plist), then:

```bash
cp deploy/com.portfolio.newsagent.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.portfolio.newsagent.plist
# to stop: launchctl unload ~/Library/LaunchAgents/com.portfolio.newsagent.plist
```

### cron alternative

```cron
# Daily at 07:00. Use absolute paths; cron has a minimal environment.
0 7 * * * cd /ABSOLUTE/PATH/TO/PROJECT && .venv/bin/python -m portfolio_news_agent.run >> agent.log 2>&1
```

## Layout

```
portfolio_news_agent/
  config.py        env + holdings.yaml loading & validation
  prompts.py       system prompt + holdings context block
  llm_client.py    Ollama chat wrapper; native + prompt tool-calling
  agent_loop.py    the tool-calling loop + guardrails
  brief.py         render final prose -> HTML + plaintext
  run.py           entry point (--dry-run, logging)
  tools/
    registry.py    tool schemas + dispatcher (URL dedupe)
    web_fetch.py   GET + trafilatura extraction
    search/        pluggable web_search
      __init__.py  SearchProvider interface + get_provider()
      searxng.py   local SearXNG JSON API backend (default)
      _throttle.py token bucket + retry/backoff (ported from web_search MCP)
      serpapi.py
      cache.py     per-day on-disk result cache
  deliver/
    email.py       SMTP multipart send
deploy/com.portfolio.newsagent.plist   launchd job (daily pre-market)
test_smoke.py      mocked end-to-end smoke tests
requirements.txt · .env.example · holdings.yaml · .gitignore
```
