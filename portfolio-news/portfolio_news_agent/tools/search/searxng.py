"""SearXNG provider — queries a locally-hosted SearXNG JSON API. No API key.

Points at the same SearXNG instance the SearXNG MCP server uses (default
``http://localhost:8080``). Throttle protection (token-bucket spacing +
exponential backoff/retry on 429/5xx) is ported from that MCP server via
:mod:`._throttle`, so direct-from-agent queries behave the same way.

Result caching is handled one layer up by the dispatcher's per-day
``SearchCache``; this provider only does the network call + throttling.
"""
from __future__ import annotations

import logging

import requests

from . import SearchProvider, SearchResult
from ._throttle import RateLimitExceededError, TokenBucket, request_with_retry

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "portfolio-news-agent/0.1 (+local searxng)"}


class SearxngProvider(SearchProvider):
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        *,
        rate_limit_rps: float = 1.0,
        rate_limit_burst: int = 3,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self._limiter = TokenBucket(rate=rate_limit_rps, capacity=rate_limit_burst)
        # Read by the dispatcher's anti-hallucination guard.
        self.throttled_count = 0

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        params = {
            "q": query,
            "format": "json",
            "categories": "general",
            "language": "auto",
            "safesearch": 1,
        }
        url = f"{self.base_url}/search"
        try:
            resp = request_with_retry(
                self._session,
                "GET",
                url,
                params=params,
                limiter=self._limiter,
                max_retries=self.max_retries,
                base=self.backoff_base,
                cap=self.backoff_max,
                timeout=self.timeout,
            )
        except RateLimitExceededError as e:
            self.throttled_count += 1
            log.warning("searxng rate-limited for %r: %s; returning no results", query, e)
            return []
        except requests.HTTPError as e:
            log.warning("searxng HTTP error for %r: %s; returning no results", query, e)
            return []
        except requests.RequestException as e:
            log.warning(
                "could not reach searxng at %s for %r: %s; is the docker container up? "
                "returning no results",
                self.base_url,
                query,
                e,
            )
            return []

        try:
            payload = resp.json()
        except ValueError:
            log.warning(
                "searxng did not return JSON for %r; is 'json' enabled under "
                "search.formats in settings.yml? returning no results",
                query,
            )
            return []

        raw = payload.get("results", []) or []
        results: list[SearchResult] = []
        for item in raw:
            url_ = item.get("url") or ""
            if not url_:
                continue
            results.append(
                SearchResult(
                    title=(item.get("title") or "(no title)").strip(),
                    url=url_,
                    snippet=(item.get("content") or "").strip(),
                )
            )
            if len(results) >= max_results:
                break
        log.info("searxng: %d results for %r", len(results), query)
        return results
