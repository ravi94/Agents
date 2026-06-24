"""SearXNG search tool.

Hits a local SearXNG instance with ?format=json. The SearXNG instance must have
the `json` format enabled in its settings.yml (under `search.formats`).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from web_researcher.config import Settings

# Cheap denylist to cut social-media / paywalled noise. Tweak as needed.
_DENY_HOSTS = {
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "pinterest.com",
    "tiktok.com",
}


class SearchInput(BaseModel):
    query: str = Field(..., description="The search query")
    max_results: int = Field(
        default=8, description="Maximum number of results to return (1-15)"
    )


def _dedupe_and_filter(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in items:
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        host = httpx.URL(url).host.lower()
        if any(host == h or host.endswith("." + h) for h in _DENY_HOSTS):
            continue
        seen.add(url)
        out.append(
            {
                "title": (r.get("title") or "").strip(),
                "url": url,
                "snippet": (r.get("content") or "").strip(),
                "engine": r.get("engine") or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def make_search_tool(settings: Settings) -> StructuredTool:
    """Build a Search tool bound to the given settings."""

    def _search(query: str, max_results: int = 8) -> str:
        max_results = max(1, min(int(max_results), 15))
        url = f"{settings.searxng_url.rstrip('/')}/search"
        params = {
            "q": query,
            "format": "json",
            "safesearch": 1,
            "language": "en",
        }
        try:
            with httpx.Client(timeout=settings.request_timeout_seconds) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            return json.dumps(
                {"error": f"SearXNG request failed: {e}", "results": []}
            )
        except json.JSONDecodeError:
            return json.dumps(
                {
                    "error": (
                        "SearXNG did not return JSON — make sure 'json' is in "
                        "search.formats in your settings.yml"
                    ),
                    "results": [],
                }
            )

        results = _dedupe_and_filter(data.get("results", []), max_results)
        return json.dumps({"results": results}, ensure_ascii=False)

    return StructuredTool.from_function(
        func=_search,
        name="search_web",
        description=(
            "Search the web via SearXNG. Use this to find candidate sources for a "
            "topic or fact. Returns a JSON object with a 'results' list, each item "
            "having title, url, snippet, engine. Call fetch_page on promising URLs."
        ),
        args_schema=SearchInput,
    )
