"""Wrapper over Ollama's OpenAI-compatible /chat/completions endpoint.

Supports two tool-calling modes:
- "native": pass `tools` to the API and read back `message.tool_calls` (OpenAI style).
- "prompt": some local builds ignore `tools`. Instead we inject the schemas into the
  system prompt and ask the model to emit a JSON object in its content; we parse it back
  into ToolCalls. The agent loop is identical for both modes.
- "auto" (default): try native; if the API returns no tool_calls, also scan the content
  for a prompt-style tool-call block. This tolerates builds that partially support tools.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

# The model is asked to emit exactly this when it wants a tool (prompt mode).
TOOL_CALL_INSTRUCTIONS = """\

TOOL CALLING: To use a tool, respond with ONLY a JSON object on its own, no prose:
{"tool_call": {"name": "<tool_name>", "arguments": { ... }}}
Available tools:
%s
When you are finished and want to write the final brief, respond with prose and NO JSON.
"""

# Matches a {"tool_call": {...}} object anywhere in the content.
_TOOL_CALL_RE = re.compile(r'\{\s*"tool_call"\s*:\s*\{.*\}\s*\}', re.DOTALL)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

    @property
    def is_valid(self) -> bool:
        return self.name != "" and isinstance(self.arguments, dict)


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    def __init__(self, base_url: str, model: str, timeout: int = 120, tool_mode: str = "auto"):
        if tool_mode not in ("native", "prompt", "auto"):
            raise ValueError(f"unknown tool_mode: {tool_mode!r}")
        self.url = f"{base_url}/chat/completions"
        self.model = model
        self.timeout = timeout
        self.tool_mode = tool_mode

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": self._prepare_messages(messages, tools),
            "temperature": 0.2,
        }
        # In prompt mode we deliberately omit `tools` so the model relies on the prompt.
        if tools and self.tool_mode != "prompt":
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = requests.post(self.url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]

        content = msg.get("content") or ""
        native = _parse_tool_calls(msg.get("tool_calls") or [])
        if native:
            return LLMResponse(content=content, tool_calls=native)

        # No native tool_calls. In prompt/auto mode, try to parse a tool call from content.
        if tools and self.tool_mode in ("prompt", "auto"):
            parsed = _parse_prompt_tool_call(content)
            if parsed:
                return LLMResponse(content="", tool_calls=[parsed])

        return LLMResponse(content=content, tool_calls=[])

    def _prepare_messages(self, messages: list[dict], tools: list[dict]) -> list[dict]:
        """In prompt mode, append tool instructions to the system message."""
        if not tools or self.tool_mode != "prompt":
            return messages
        out = [dict(m) for m in messages]
        instructions = TOOL_CALL_INSTRUCTIONS % _schema_summary(tools)
        for m in out:
            if m.get("role") == "system":
                m["content"] = m.get("content", "") + instructions
                return out
        out.insert(0, {"role": "system", "content": instructions})
        return out


def _schema_summary(tools: list[dict]) -> str:
    lines = []
    for t in tools:
        fn = t.get("function", {})
        lines.append(
            f'- {fn.get("name")}: {fn.get("description","")} '
            f'params={json.dumps(fn.get("parameters", {}).get("properties", {}))}'
        )
    return "\n".join(lines)


def _parse_tool_calls(raw: list[dict]) -> list[ToolCall]:
    """Parse OpenAI-style tool_calls; tolerate malformed JSON args (caller retries)."""
    calls: list[ToolCall] = []
    for tc in raw:
        fn = tc.get("function", {})
        raw_args = fn.get("arguments", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except json.JSONDecodeError:
            log.warning("malformed tool args for %s: %r", fn.get("name"), raw_args)
            args = {}
        calls.append(
            ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args)
        )
    return calls


def _parse_prompt_tool_call(content: str) -> ToolCall | None:
    """Extract a {"tool_call": {...}} object from prompt-mode content, if present."""
    if "tool_call" not in content:
        return None
    match = _TOOL_CALL_RE.search(content)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        call = obj["tool_call"]
        name = str(call["name"])
        args = call.get("arguments", {})
        if not isinstance(args, dict):
            args = {}
        return ToolCall(id=f"prompt-{uuid.uuid4().hex[:8]}", name=name, arguments=args)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning("failed to parse prompt tool call: %s", e)
        return None
