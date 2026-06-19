"""Tool schemas (sent to the LLM each turn) and a dispatcher to execute tool calls."""
from __future__ import annotations

import json
import logging

from ..config import Config
from . import web_fetch
from .search import get_provider
from .search.cache import SearchCache

log = logging.getLogger(__name__)

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for recent news. Returns a list of {title, url, snippet}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Max results to return (1-10).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a URL and return its cleaned main article text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch."}
                },
                "required": ["url"],
            },
        },
    },
]


class ToolDispatcher:
    """Executes tool calls by name. Dedupes fetched URLs within a run."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.search_provider = get_provider(cfg)
        self.search_cache = SearchCache(
            cfg.search_cache_dir, cfg.search_provider, cfg.search_cache_enabled
        )
        self._fetched: dict[str, str] = {}
        # Grounding counters — used by the agent loop's anti-hallucination guard.
        self.search_calls = 0
        self.search_hits = 0  # searches that returned >= 1 result
        self.fetch_hits = 0  # fetches that returned usable article text

    @property
    def has_grounding(self) -> bool:
        """True if any tool actually returned real content to base a brief on."""
        return self.search_hits > 0 or self.fetch_hits > 0

    @property
    def throttled(self) -> bool:
        """True if the search backend reported being rate-limited/blocked this run."""
        count = getattr(self.search_provider, "throttled_count", 0)
        return isinstance(count, int) and count > 0

    def dispatch(self, name: str, args: dict) -> str:
        """Run a tool, return a string result for the `tool` message. Never raises."""
        try:
            if name == "web_search":
                return self._web_search(args)
            if name == "web_fetch":
                return self._web_fetch(args)
            return f"[unknown tool: {name}]"
        except Exception as e:  # tool failures must not crash the loop
            log.warning("tool %s failed: %s", name, e)
            return f"[tool error: {e}]"

    def _web_search(self, args: dict) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "[web_search error: empty query]"
        max_results = min(int(args.get("max_results", 5) or 5), 10)
        self.search_calls += 1
        cached = self.search_cache.get(query, max_results)
        if cached is not None:
            log.info("web_search cache hit for %r (%d results)", query, len(cached))
            if cached:
                self.search_hits += 1
            return json.dumps(cached)
        results = self.search_provider.search(query, max_results)
        payload = [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results]
        if payload:
            self.search_hits += 1
        self.search_cache.put(query, max_results, payload)
        return json.dumps(payload)

    def _web_fetch(self, args: dict) -> str:
        url = str(args.get("url", "")).strip()
        if not url:
            return "[web_fetch error: empty url]"
        if url in self._fetched:
            return self._fetched[url]
        text = web_fetch.fetch(url, self.cfg.fetch_char_budget)
        self._fetched[url] = text
        if text and not text.startswith("["):  # not an "[error ...]" placeholder
            self.fetch_hits += 1
        return text
