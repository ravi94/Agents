"""Page fetch + main-content extraction."""

from __future__ import annotations

import json

import httpx
import trafilatura
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from web_researcher.config import Settings

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 web-researcher/0.1"
)


class FetchInput(BaseModel):
    url: str = Field(..., description="Fully-qualified URL to fetch")


def make_fetch_tool(settings: Settings) -> StructuredTool:
    def _fetch(url: str) -> str:
        try:
            with httpx.Client(
                timeout=settings.request_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                html = resp.text
        except httpx.HTTPError as e:
            return json.dumps({"error": f"Fetch failed: {e}", "url": url})

        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        if not extracted:
            return json.dumps(
                {
                    "error": "Could not extract main content (likely JS-rendered)",
                    "url": url,
                }
            )

        # Cheap title pull from <title>
        title = ""
        if "<title" in html:
            try:
                start = html.index("<title")
                start = html.index(">", start) + 1
                end = html.index("</title>", start)
                title = html[start:end].strip()
            except ValueError:
                title = ""

        text = extracted.strip()
        truncated = False
        if len(text) > settings.max_page_chars:
            text = text[: settings.max_page_chars]
            truncated = True

        return json.dumps(
            {
                "url": url,
                "title": title,
                "text": text,
                "truncated": truncated,
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        func=_fetch,
        name="fetch_page",
        description=(
            "Fetch a web page by URL and return the cleaned main article text "
            "(no nav/ads/footer). Use this on promising URLs from search_web. "
            "If 'truncated' is true, call summarize_chunk to compress the text "
            "toward your current question."
        ),
        args_schema=FetchInput,
    )
