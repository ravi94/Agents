"""T031 [US2] — Adzuna (India) source adapter.

Maps ``SearchQuery`` objects onto Adzuna's India job-search endpoint, one
request per query, routed through the shared ``http.py`` wrapper (caching +
429 backoff) and gated on the ``ADZUNA_APP_ID``/``ADZUNA_APP_KEY``
credentials so a missing key is reported as "source unavailable"
(``SourceError``) rather than a crash. Unlike JSearch's RapidAPI header auth,
Adzuna's auth model is query-param based. Returns raw, source-shaped
postings only — see ``discovery/normalize.py`` for the mapping to the
canonical ``Job``.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from jobhunter import http, obs
from jobhunter.sources import cache
from jobhunter.sources.base import RawPosting, SearchQuery, SourceError

APP_ID_ENV = "ADZUNA_APP_ID"
APP_KEY_ENV = "ADZUNA_APP_KEY"
BASE_URL = "https://api.adzuna.com/v1/api/jobs/in/search/1"
DEFAULT_BUDGET = 5
RESULTS_PER_PAGE = 10


class AdzunaSource:
    """``JobSource`` adapter for the Adzuna India job-search endpoint."""

    name = "adzuna"

    def __init__(
        self,
        app_id: str | None = None,
        app_key: str | None = None,
        *,
        budget: int = DEFAULT_BUDGET,
        client: httpx.Client | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_key = app_key
        self._budget = budget
        self._client = client
        self._cache_dir = cache_dir

    def fetch(self, queries: list[SearchQuery]) -> list[RawPosting]:
        """Issue up to ``budget`` Adzuna lookups and return flattened raw postings."""
        app_id = self._app_id or os.environ.get(APP_ID_ENV)
        app_key = self._app_key or os.environ.get(APP_KEY_ENV)
        if not app_id or not app_key:
            raise SourceError(f"{APP_ID_ENV} and {APP_KEY_ENV} must both be set")

        postings: list[RawPosting] = []
        with obs.trace("source.fetch", source=self.name):
            for query in queries[: self._budget]:
                postings.extend(self._fetch_one(query, app_id, app_key))
        return postings

    def _fetch_one(self, query: SearchQuery, app_id: str, app_key: str) -> list[RawPosting]:
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": RESULTS_PER_PAGE,
            "what": query.keywords,
            "where": query.location,
        }

        payload = cache.get("adzuna", "search", params, cache_dir=self._cache_dir)
        if payload is None:
            payload = self._live_fetch(params)
            cache.set("adzuna", "search", params, payload, cache_dir=self._cache_dir)

        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise SourceError("adzuna 'results' field is not a list")
        return payload["results"]

    def _live_fetch(self, params: dict) -> dict:
        try:
            response = http.get(BASE_URL, params=params, client=self._client)
        except (http.RateLimitExceeded, httpx.HTTPError) as exc:
            raise SourceError(f"adzuna request failed: {exc}") from exc

        if response.status_code != 200:
            raise SourceError(f"adzuna returned status {response.status_code}")

        try:
            return response.json()
        except ValueError as exc:
            raise SourceError("adzuna returned a non-JSON response") from exc
