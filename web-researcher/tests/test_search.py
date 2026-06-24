"""Unit tests for the search tool — uses respx to mock SearXNG."""

from __future__ import annotations

import json

import httpx
import respx

from web_researcher.config import Settings
from web_researcher.tools.search import make_search_tool


def _settings() -> Settings:
    return Settings(searxng_url="http://searx.test")  # type: ignore[call-arg]


@respx.mock
def test_search_returns_filtered_results():
    respx.get("http://searx.test/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Real", "url": "https://example.com/a", "content": "snip", "engine": "google"},
                    {"title": "Dup", "url": "https://example.com/a", "content": "dup", "engine": "bing"},
                    {"title": "Social", "url": "https://twitter.com/x", "content": "nope", "engine": "google"},
                    {"title": "Second", "url": "https://example.org/b", "content": "snip2", "engine": "google"},
                ]
            },
        )
    )

    tool = make_search_tool(_settings())
    raw = tool.invoke({"query": "anything", "max_results": 5})
    data = json.loads(raw)

    urls = [r["url"] for r in data["results"]]
    assert urls == ["https://example.com/a", "https://example.org/b"]


@respx.mock
def test_search_handles_non_json_response():
    respx.get("http://searx.test/search").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    tool = make_search_tool(_settings())
    data = json.loads(tool.invoke({"query": "x"}))
    assert "error" in data
    assert data["results"] == []
