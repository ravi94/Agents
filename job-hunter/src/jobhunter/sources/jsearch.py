"""T019 [US2] — JSearch (RapidAPI) source adapter.

Maps ``SearchQuery`` objects onto JSearch's ``/search-v2`` endpoint, one request
per query, routed through the shared ``http.py`` wrapper (caching + 429
backoff) and gated on the ``JSEARCH_API_KEY`` credential so a missing key is
reported as "source unavailable" (``SourceError``) rather than a crash.
Returns raw, source-shaped postings only — see ``discovery/normalize.py`` for
the mapping to the canonical ``Job``.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from jobhunter import http, obs
from jobhunter.sources import cache
from jobhunter.sources.base import RawPosting, SearchQuery, SourceError

API_KEY_ENV = "JSEARCH_API_KEY"
BASE_URL = "https://jsearch.p.rapidapi.com/search-v2"
API_HOST = "jsearch.p.rapidapi.com"
DEFAULT_BUDGET = 5


class JSearchSource:
    """``JobSource`` adapter for the JSearch RapidAPI job-search endpoint."""

    name = "jsearch"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        budget: int = DEFAULT_BUDGET,
        client: httpx.Client | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._api_key = api_key
        self._budget = budget
        self._client = client
        self._cache_dir = cache_dir

    def fetch(self, queries: list[SearchQuery]) -> list[RawPosting]:
        """Issue up to ``budget`` JSearch lookups and return flattened raw postings."""
        api_key = self._api_key or os.environ.get(API_KEY_ENV)
        if not api_key:
            raise SourceError(f"{API_KEY_ENV} not set")

        postings: list[RawPosting] = []
        with obs.trace("source.fetch", source=self.name):
            for query in queries[: self._budget]:
                postings.extend(self._fetch_one(query, api_key))
        return postings

    def _fetch_one(self, query: SearchQuery, api_key: str) -> list[RawPosting]:
        params = {
            "query": f"{query.keywords} in {query.location}",
            "page": 1,
            "num_pages": 1,
        }

        payload = cache.get("jsearch", "search", params, cache_dir=self._cache_dir)
        if payload is None:
            payload = self._live_fetch(params, api_key)
            cache.set("jsearch", "search", params, payload, cache_dir=self._cache_dir)

        if not isinstance(payload, dict) or "data" not in payload:
            raise SourceError("jsearch response missing 'data'")

        data = payload["data"]
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise SourceError("jsearch 'data.jobs' field is not a list")
        return data["jobs"]

    def _live_fetch(self, params: dict, api_key: str) -> dict:
        headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": API_HOST}
        try:
            response = http.get(BASE_URL, params=params, headers=headers, client=self._client)
        except (http.RateLimitExceeded, httpx.HTTPError) as exc:
            raise SourceError(f"jsearch request failed: {exc}") from exc

        if response.status_code != 200:
            raise SourceError(f"jsearch returned status {response.status_code}")

        try:
            return response.json()
        except ValueError as exc:
            raise SourceError("jsearch returned a non-JSON response") from exc
