"""SerpAPI provider — Google results via API key. Higher reliability + news quality."""
from __future__ import annotations

import logging

import requests

from . import SearchProvider, SearchResult

log = logging.getLogger(__name__)

_ENDPOINT = "https://serpapi.com/search.json"


class SerpApiProvider(SearchProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        params = {
            "engine": "google",
            "q": query,
            "num": max_results,
            "api_key": self.api_key,
        }
        resp = requests.get(_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        # Prefer fresh news_results, fall back to organic_results.
        rows = data.get("news_results") or data.get("organic_results") or []
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", "") or r.get("source", ""),
            )
            for r in rows
            if r.get("link")
        ][:max_results]
        log.info("serpapi: %d results for %r", len(results), query)
        return results
