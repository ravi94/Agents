"""Pluggable web search. The agent sees one `web_search` tool; the backend is config-driven."""
from __future__ import annotations

from dataclasses import dataclass

from ...config import Config


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchProvider:
    """Common interface. Adding Tavily/Brave = a new subclass + a line in get_provider."""

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise NotImplementedError


def get_provider(cfg: Config) -> SearchProvider:
    if cfg.search_provider == "serpapi":
        from .serpapi import SerpApiProvider

        if not cfg.serpapi_api_key:
            raise ValueError("SEARCH_PROVIDER=serpapi but SERPAPI_API_KEY is not set")
        return SerpApiProvider(cfg.serpapi_api_key)
    from .duckduckgo import DuckDuckGoProvider

    return DuckDuckGoProvider(
        min_interval=cfg.search_min_interval, jitter=cfg.search_jitter
    )
