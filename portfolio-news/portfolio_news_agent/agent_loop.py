"""The agent loop: build prompt → call LLM → dispatch tools → feed back → stop on no tool_calls."""
from __future__ import annotations

import logging
import time

from .config import Config
from .llm_client import LLMClient
from .prompts import SYSTEM_PROMPT, build_holdings_block
from .tools.registry import TOOL_SCHEMAS, ToolDispatcher

log = logging.getLogger(__name__)


def run_agent(cfg: Config) -> str:
    """Drive the tool-calling loop and return the final brief text."""
    client = LLMClient(cfg.ollama_base_url, cfg.model_name, tool_mode=cfg.tool_mode)
    dispatcher = ToolDispatcher(cfg)

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_holdings_block(cfg.holdings)},
    ]

    deadline = time.monotonic() + cfg.run_timeout_seconds
    tool_calls_made = 0

    for iteration in range(1, cfg.max_iterations + 1):
        if time.monotonic() > deadline:
            log.warning("run timeout hit; forcing final summary")
            return _finalize(_force_final(client, messages), dispatcher)

        log.info("iteration %d/%d", iteration, cfg.max_iterations)
        resp = client.chat(messages, TOOL_SCHEMAS)

        if not resp.wants_tools:
            log.info("model returned final brief (%d chars)", len(resp.content))
            return _finalize(resp.content, dispatcher)

        # Append the assistant turn (with its tool_calls) before tool results.
        messages.append(_assistant_msg(resp))

        for tc in resp.tool_calls:
            if tool_calls_made >= cfg.max_tool_calls:
                log.warning("max tool calls (%d) reached; forcing final summary", cfg.max_tool_calls)
                return _finalize(_force_final(client, messages), dispatcher)
            tool_calls_made += 1
            log.info("tool[%d] %s args=%s", tool_calls_made, tc.name, tc.arguments)
            result = dispatcher.dispatch(tc.name, tc.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result,
                }
            )

    log.warning("max iterations (%d) reached; forcing final summary", cfg.max_iterations)
    return _finalize(_force_final(client, messages), dispatcher)


def _finalize(brief: str, dispatcher: ToolDispatcher) -> str:
    """Anti-hallucination guard: if the run gathered no real evidence, don't trust the
    model's brief — it has nothing to ground claims on, so report unavailability instead.
    """
    if dispatcher.has_grounding:
        return brief
    if dispatcher.throttled:
        msg = (
            "Could not retrieve news: the web search backend was unavailable "
            "(rate-limited / blocked) — every search this run was throttled. No brief "
            "was generated to avoid reporting unverified information. Try again later, "
            "or switch SEARCH_PROVIDER (e.g. serpapi)."
        )
    elif dispatcher.search_calls > 0:
        msg = (
            "Could not retrieve news: web search returned no results for any holding. "
            "No brief was generated to avoid reporting unverified information."
        )
    else:
        msg = (
            "Could not retrieve news: no searches were performed, so there is nothing to "
            "report. No brief was generated to avoid reporting unverified information."
        )
    log.warning(
        "anti-hallucination guard tripped (%d searches, %d hits, %d fetch hits, throttled=%s);"
        " replacing model brief",
        dispatcher.search_calls,
        dispatcher.search_hits,
        dispatcher.fetch_hits,
        dispatcher.throttled,
    )
    return msg


def _assistant_msg(resp) -> dict:
    return {
        "role": "assistant",
        "content": resp.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": _dump_args(tc.arguments)},
            }
            for tc in resp.tool_calls
        ],
    }


def _dump_args(args: dict) -> str:
    import json

    return json.dumps(args)


def _force_final(client: LLMClient, messages: list[dict]) -> str:
    """Ask the model to summarize now with no further tools."""
    messages.append(
        {
            "role": "user",
            "content": "Stop searching now and write the final brief from what you have.",
        }
    )
    resp = client.chat(messages, tools=[])
    return resp.content or "[no brief produced]"
