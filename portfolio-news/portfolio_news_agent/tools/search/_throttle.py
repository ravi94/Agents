"""Client-side rate limiting and retry/backoff for talking to SearXNG.

A synchronous port of the logic in the SearXNG MCP server
(``mcp/web_search/src/searxng_mcp/ratelimit.py``), so the agent gets the same
throttle protection when it queries SearXNG directly.

SearXNG used as a JSON API tends to surface ``429 Too Many Requests`` when its
upstream engines (Google, Bing, ...) throttle it. Two defenses:

1. :class:`TokenBucket` proactively *spaces out* outgoing requests so we never
   hammer SearXNG (or, transitively, its upstreams).
2. :func:`request_with_retry` reactively *retries with exponential backoff +
   jitter* on 429/5xx, honoring a ``Retry-After`` header when present.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any

import requests


class RateLimitExceededError(RuntimeError):
    """Raised when retries are exhausted while being rate limited."""


class TokenBucket:
    """A simple thread-safe token bucket.

    ``rate`` tokens are added per second up to ``capacity``. Each
    :meth:`acquire` consumes one token, sleeping if none are available.
    """

    def __init__(self, rate: float, capacity: int) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._rate = rate
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._updated = now

    def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
            # Sleep outside the lock so other threads can refill/observe.
            time.sleep(deficit / self._rate)


def _retry_after_seconds(response: requests.Response) -> float | None:
    """Parse a ``Retry-After`` header (delta-seconds form) if present."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        # HTTP-date form is uncommon for 429s here; fall back to backoff.
        return None


def _backoff(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with full jitter."""
    expo = min(cap, base * (2 ** attempt))
    return expo + random.uniform(0, base)


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    limiter: TokenBucket,
    max_retries: int,
    base: float,
    cap: float,
    **kwargs: Any,
) -> requests.Response:
    """Issue an HTTP request through ``limiter`` with retry on 429/5xx.

    Returns the successful :class:`requests.Response`. Raises
    :class:`RateLimitExceededError` if all retries are exhausted on a 429, or
    re-raises the last error/response for other failures.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        limiter.acquire()
        try:
            response = session.request(method, url, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as exc:
            # Network-level hiccup: back off and retry.
            last_exc = exc
            if attempt >= max_retries:
                raise
            time.sleep(_backoff(attempt, base, cap))
            continue

        if response.status_code == 429 or response.status_code >= 500:
            if attempt >= max_retries:
                if response.status_code == 429:
                    raise RateLimitExceededError(
                        f"SearXNG rate-limited the request (429) after "
                        f"{max_retries + 1} attempts."
                    )
                response.raise_for_status()
            delay = _retry_after_seconds(response)
            if delay is None:
                delay = _backoff(attempt, base, cap)
            time.sleep(delay)
            continue

        return response

    # Only reached if the loop fell through on a network exception path.
    assert last_exc is not None
    raise last_exc
