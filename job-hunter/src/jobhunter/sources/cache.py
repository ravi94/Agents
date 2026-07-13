"""T008 [Foundational] — file-based response cache (free-tier protection).

A cache under ``cache/`` in the app data directory, keyed by a hash of
``(source, endpoint, normalized params)``; each entry stores the raw response
plus the timestamp it was cached at. A hit within the TTL is served without an
external call; a miss or an expired entry is reported as absent so the caller
re-fetches and re-``set``s (FR-005). Zero-dependency (stdlib only) and
inspectable, consistent with local-first storage (research.md §2). Cache
entries carry no personal data — only query params and public responses
(FR-021).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jobhunter import config

DEFAULT_TTL_SECONDS = 6 * 3600


def _cache_key(source: str, endpoint: str, params: dict) -> str:
    normalized = json.dumps(params, sort_keys=True, default=str)
    raw = f"{source}|{endpoint}|{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _entry_path(source: str, endpoint: str, params: dict, cache_dir: Path) -> Path:
    return cache_dir / f"{_cache_key(source, endpoint, params)}.json"


def get(
    source: str,
    endpoint: str,
    params: dict,
    *,
    cache_dir: Path | None = None,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    now: Callable[[], float] = time.time,
) -> Any | None:
    """Return the cached response for ``(source, endpoint, params)``, or ``None``.

    ``None`` covers both a cache miss and an entry older than ``ttl_seconds`` —
    either way, the caller should re-fetch and ``set`` the fresh response.
    """
    path = _entry_path(source, endpoint, params, cache_dir or config.cache_dir())
    if not path.exists():
        return None
    entry = json.loads(path.read_text())
    if now() - entry["cached_at"] > ttl_seconds:
        return None
    return entry["response"]


def set(
    source: str,
    endpoint: str,
    params: dict,
    response: Any,
    *,
    cache_dir: Path | None = None,
    now: Callable[[], float] = time.time,
) -> Path:
    """Cache ``response`` for ``(source, endpoint, params)``, stamped with the current time."""
    target_dir = cache_dir or config.cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = _entry_path(source, endpoint, params, target_dir)
    path.write_text(json.dumps({"cached_at": now(), "response": response}))
    return path
