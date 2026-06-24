"""Unit tests for the fetch tool."""

from __future__ import annotations

import json

import httpx
import respx

from web_researcher.config import Settings
from web_researcher.tools.fetch import make_fetch_tool


def _settings(max_chars: int = 12_000) -> Settings:
    return Settings(searxng_url="http://searx.test", max_page_chars=max_chars)  # type: ignore[call-arg]


_HTML = """
<html><head><title>Hello World</title></head>
<body>
  <nav>menu menu menu</nav>
  <article>
    <h1>Main Story</h1>
    <p>This is the actual article body. It has multiple sentences explaining a topic
    in a way that trafilatura will recognize as the main content of the page.</p>
    <p>Second paragraph with more detail and substance for extraction.</p>
  </article>
  <footer>footer junk</footer>
</body></html>
"""


@respx.mock
def test_fetch_extracts_main_content():
    respx.get("https://example.com/article").mock(
        return_value=httpx.Response(200, text=_HTML)
    )
    tool = make_fetch_tool(_settings())
    data = json.loads(tool.invoke({"url": "https://example.com/article"}))

    assert data["url"] == "https://example.com/article"
    assert data["title"] == "Hello World"
    assert "Main Story" in data["text"] or "actual article body" in data["text"]
    assert data["truncated"] is False


@respx.mock
def test_fetch_truncates_long_text():
    long_html = "<html><head><title>X</title></head><body><article>" \
                + ("<p>" + ("word " * 200) + "</p>") * 20 + "</article></body></html>"
    respx.get("https://example.com/big").mock(
        return_value=httpx.Response(200, text=long_html)
    )
    tool = make_fetch_tool(_settings(max_chars=500))
    data = json.loads(tool.invoke({"url": "https://example.com/big"}))
    assert data["truncated"] is True
    assert len(data["text"]) == 500


@respx.mock
def test_fetch_handles_http_error():
    respx.get("https://example.com/dead").mock(return_value=httpx.Response(500))
    tool = make_fetch_tool(_settings())
    data = json.loads(tool.invoke({"url": "https://example.com/dead"}))
    assert "error" in data
