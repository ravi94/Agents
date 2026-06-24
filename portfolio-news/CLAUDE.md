# CLAUDE.md

Guidance for Claude Code (and future contributors) when working in this repository.

## What this is

A scheduled **tool-calling agent**. On each run it loads your stock holdings, lets a
local LLM (Qwen via Ollama) decide what to research using `web_search` / `web_fetch`,
loops until the model stops calling tools, then emails (or saves) a synthesized news
brief — one section per holding.

The defining property: **the LLM drives the loop, not a fixed pipeline.** The model
decides what to search, which articles to read, and when it has gathered enough.

See [design.md](design.md) for the architecture rationale and [README.md](README.md)
for setup/run steps. A visual of the full code flow lives in
[architecture.svg](architecture.svg).

## Commands

```bash
# Setup
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # then fill in SMTP creds / SERPAPI_API_KEY

# Run (dry-run prints the brief to stdout; no email sent, no email config needed)
.venv/bin/python -m portfolio_news_agent.run --dry-run
.venv/bin/python -m portfolio_news_agent.run

# Offline tests — LLM + network are mocked; no Ollama or internet required
.venv/bin/python test_smoke.py
```

Ollama must be running with the model named in `.env` (`ollama serve` +
`ollama pull qwen3:27b`). Logs go to **stderr**; the brief goes to **stdout** under
`--dry-run` — keep that separation intact so piping the brief stays clean.

## Architecture (code flow)

```
run.py  (entry point, --dry-run, logging, fail-fast email validation)
  └─ config.load_config()        .env + holdings.yaml -> typed Config/Holding
  └─ agent_loop.run_agent(cfg)   THE LOOP:
        system + holdings prompt -> LLMClient.chat() ⇄ ToolDispatcher
        repeat until the model returns prose (no tool_calls) or a guardrail trips
  └─ brief.py                    prose -> subject + HTML + plaintext
  └─ deliver/ email.py | file.py
```

Module responsibilities:

| Module | Responsibility |
|---|---|
| [config.py](portfolio_news_agent/config.py) | Load env/`.env` + `holdings.yaml`; validate; expose typed `Config` + `Holding` |
| [prompts.py](portfolio_news_agent/prompts.py) | System prompt (analyst role, news-only, grounding rules) + holdings block |
| [llm_client.py](portfolio_news_agent/llm_client.py) | Ollama chat wrapper; `native` / `prompt` / `auto` tool-calling; normalize to `ToolCall` |
| [agent_loop.py](portfolio_news_agent/agent_loop.py) | Orchestrate the loop; guardrails; anti-hallucination guard |
| [tools/registry.py](portfolio_news_agent/tools/registry.py) | Tool JSON schemas + `ToolDispatcher` (URL dedupe, grounding counters, never raises) |
| [tools/web_fetch.py](portfolio_news_agent/tools/web_fetch.py) | GET URL -> trafilatura main-text extraction, truncated to a char budget |
| [tools/search/](portfolio_news_agent/tools/search/) | Pluggable `web_search`: `SearchProvider` interface + `searxng` (default, local SearXNG JSON API w/ token-bucket + retry/backoff in `_throttle.py`) / `serpapi` + per-day cache |
| [brief.py](portfolio_news_agent/brief.py) | Render final prose -> linkified HTML + plaintext; build subject |
| [deliver/email.py](portfolio_news_agent/deliver/email.py) | SMTP STARTTLS multipart HTML+text send |
| [deliver/file.py](portfolio_news_agent/deliver/file.py) | Write `summary-<date>.md` to `OUTPUT_DIR` |
| [run.py](portfolio_news_agent/run.py) | Entry point the scheduler calls |

## Conventions & invariants (don't break these)

- **The loop only ever sees `ToolCall` objects.** All tool-calling-mode complexity is
  contained in `llm_client.py`. If you add a mode, normalize it there — never branch on
  `tool_mode` inside `agent_loop.py`.
- **Tools must never raise into the loop.** `ToolDispatcher.dispatch` catches everything
  and returns an `[error ...]` string that gets fed back to the model. Preserve this.
- **Anti-hallucination guard is load-bearing.** `_finalize()` in `agent_loop.py` discards
  the model's brief and returns an honest "could not retrieve news" message when the run
  gathered no real evidence (`search_hits`/`fetch_hits` both zero). This is what makes a
  flaky local search backend safe for financial news. Keep the grounding counters in
  `registry.py` accurate when changing tool code.
- **Three independent guardrails:** `MAX_ITERATIONS`, `MAX_TOOL_CALLS`,
  `RUN_TIMEOUT_SECONDS`. Hitting any one triggers `_force_final()` (one last LLM call with
  no tools). Don't remove a cap without a replacement bound.
- **Search is pluggable by design.** Adding Tavily/Brave = a new file in
  `tools/search/` implementing `SearchProvider.search()` + one line in `get_provider()`.
  No agent-loop changes. Keep the `web_search` tool schema stable across providers.
- **The search cache never stores empty results** (`cache.py`) so a throttled search can
  be retried later instead of being remembered as "no news." Don't change this.
- **Secrets** (SMTP password, `SERPAPI_API_KEY`) live only in `.env`, which is gitignored.
  Never commit `.env` or hardcode credentials.

## Style

- Python 3.11+ idioms with `from __future__ import annotations` (so `X | None` works on
  3.9). Dataclasses for config/results. Module-level `log = logging.getLogger(__name__)`;
  log to stderr, not stdout.
- Keep new modules small and single-responsibility, matching the existing layout.

## Testing

`test_smoke.py` is the safety net: it mocks the LLM and tools to verify wiring end to end
(both tool modes, the loop, the guardrail cap, brief rendering, dry-run) with no Ollama
and no network. Run it before and after changes to the loop, client, or dispatcher.
