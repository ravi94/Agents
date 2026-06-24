"""Per-day on-disk cache of web_search results.

Keyed by (max_results, normalized query) within a single calendar day so repeated or
re-run searches don't re-hit the backend — both deduping within a run and surviving
across runs on the same day. Empty result sets are intentionally NOT cached, so a
throttled/blocked search can be retried later instead of being remembered as "no news".
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)


class SearchCache:
    def __init__(self, cache_dir: Path, provider: str, enabled: bool = True):
        self.enabled = enabled
        self.path = cache_dir / f"search-{provider}-{date.today().isoformat()}.json"
        self._data: dict[str, list[dict]] = {}
        if self.enabled:
            self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text()) or {}
        except (OSError, json.JSONDecodeError) as e:
            log.debug("search cache load failed (%s); starting empty", e)
            self._data = {}

    @staticmethod
    def _key(query: str, max_results: int) -> str:
        return f"{max_results}:{query.strip().lower()}"

    def get(self, query: str, max_results: int) -> list[dict] | None:
        if not self.enabled:
            return None
        return self._data.get(self._key(query, max_results))

    def put(self, query: str, max_results: int, results: list[dict]) -> None:
        if not self.enabled or not results:  # don't cache empty (likely throttled) hits
            return
        self._data[self._key(query, max_results)] = results
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2))
        except OSError as e:
            log.debug("search cache write failed: %s", e)
