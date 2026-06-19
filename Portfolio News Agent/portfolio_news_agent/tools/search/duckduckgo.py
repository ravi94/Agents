"""DuckDuckGo HTML provider — no API key. Scrapes the lite HTML endpoint with bs4.

Best-effort: this is an undocumented endpoint and may rate-limit or change markup.
To reduce throttling we (a) reuse one Session so cookies persist, (b) warm up by
hitting the homepage once to acquire those cookies, and (c) space requests apart with
a configurable minimum interval plus random jitter so a run doesn't burst.
"""
from __future__ import annotations

import logging
import random
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

from . import SearchProvider, SearchResult

log = logging.getLogger(__name__)

_ENDPOINT = "https://html.duckduckgo.com/html/"
_HOME = "https://duckduckgo.com/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _HOME,
    "Origin": "https://html.duckduckgo.com",
}


class DuckDuckGoProvider(SearchProvider):
    def __init__(self, min_interval: float = 2.0, jitter: float = 1.0):
        self.min_interval = max(0.0, min_interval)
        self.jitter = max(0.0, jitter)
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self._warmed = False
        self._last_request = 0.0
        self.throttled_count = 0  # read by the dispatcher's anti-hallucination guard

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        self._warmup()
        self._throttle()
        resp = self._session.post(_ENDPOINT, data={"q": query}, timeout=20)
        resp.raise_for_status()  # only catches 4xx/5xx, NOT the 202 throttle page
        if self._is_throttled(resp):
            self.throttled_count += 1
            log.warning(
                "duckduckgo throttled (HTTP %d, anomaly page) for %r; returning no results",
                resp.status_code,
                query,
            )
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        results: list[SearchResult] = []
        for row in soup.select("div.result"):
            a = row.select_one("a.result__a")
            if not a:
                continue
            url = _unwrap(a.get("href", ""))
            snippet_el = row.select_one(".result__snippet")
            results.append(
                SearchResult(
                    title=a.get_text(" ", strip=True),
                    url=url,
                    snippet=snippet_el.get_text(" ", strip=True) if snippet_el else "",
                )
            )
            if len(results) >= max_results:
                break
        log.info("duckduckgo: %d results for %r", len(results), query)
        return results

    def _warmup(self) -> None:
        """Hit the homepage once so the Session picks up DDG's cookies."""
        if self._warmed:
            return
        self._warmed = True
        try:
            self._session.get(_HOME, timeout=20)
        except requests.RequestException as e:  # warmup is best-effort
            log.debug("duckduckgo warmup failed: %s", e)

    def _throttle(self) -> None:
        """Sleep so requests stay >= min_interval apart, plus 0..jitter random seconds."""
        if self.min_interval <= 0 and self.jitter <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        wait = max(0.0, self.min_interval - elapsed) + random.uniform(0, self.jitter)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    @staticmethod
    def _is_throttled(resp: requests.Response) -> bool:
        # DDG serves its anti-bot page as HTTP 202 with "anomaly" in the body.
        return resp.status_code == 202 or "anomaly" in resp.text.lower()


def _unwrap(href: str) -> str:
    """DDG wraps links as /l/?uddg=<encoded-url>; unwrap to the real URL."""
    if "uddg=" in href:
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
            return qs["uddg"][0]
    if href.startswith("//"):
        return "https:" + href
    return href
