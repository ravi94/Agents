"""web_fetch tool: GET a URL, extract main article text, truncate to a char budget."""
from __future__ import annotations

import logging

import requests
import trafilatura

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def fetch(url: str, char_budget: int = 8000) -> str:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("web_fetch failed for %s: %s", url, e)
        return f"[fetch error: {e}]"

    text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
    if not text:
        return "[no extractable article text]"
    if len(text) > char_budget:
        text = text[:char_budget] + "\n…[truncated]"
    log.info("web_fetch: %d chars from %s", len(text), url)
    return text
