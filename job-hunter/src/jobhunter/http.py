"""T006 [Foundational] — the rate-limit-safe HTTP wrapper every source routes through.

A thin `httpx` (sync) wrapper enforcing one bounded retry policy with
exponential backoff on HTTP 429, honoring `Retry-After` when the source sends
one; a small fixed attempt cap, after which the caller (a source adapter)
should translate the failure into a `SourceError` (FR-006). Sync keeps the
pipeline deterministic — runs are manual and issue only a handful of requests,
so concurrency buys nothing (research.md §1).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

DEFAULT_TIMEOUT = 25.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0


class RateLimitExceeded(Exception):
    """Raised when a source is still rate-limited (HTTP 429) after bounded retries."""


def get(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    client: httpx.Client | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    timeout: float = DEFAULT_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """GET ``url``, retrying on HTTP 429 within bounded limits.

    On a 429, sleeps for the response's ``Retry-After`` header if present,
    else an exponentially growing delay (``backoff_base * 2**attempt``), then
    retries. After ``max_retries`` retries are exhausted, raises
    :class:`RateLimitExceeded` rather than returning the 429 response.
    """
    owns_client = client is None
    http_client = client or httpx.Client(timeout=timeout)
    try:
        attempt = 0
        while True:
            response = http_client.get(url, params=params, headers=headers)
            if response.status_code != 429:
                return response
            attempt += 1
            if attempt > max_retries:
                raise RateLimitExceeded(
                    f"still rate-limited after {max_retries} retries: {url}"
                )
            sleep(_retry_delay(response, attempt, backoff_base))
    finally:
        if owns_client:
            http_client.close()


def _retry_delay(response: httpx.Response, attempt: int, backoff_base: float) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return backoff_base * (2 ** (attempt - 1))
