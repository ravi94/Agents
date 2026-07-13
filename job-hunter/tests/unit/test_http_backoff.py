"""T005 [Foundational] — unit tests for the rate-limit-safe HTTP wrapper.

Covers bounded retries on HTTP 429, exponential backoff between attempts, and
honoring a `Retry-After` header when present. Written first (Constitution
VII) — expected to fail until T006 implements `jobhunter.http`.
"""

import httpx
import pytest

from jobhunter import http


def _responses_transport(status_codes, headers_by_call=None):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        index = calls["count"]
        calls["count"] += 1
        status = status_codes[index]
        headers = (headers_by_call or {}).get(index, {})
        return httpx.Response(status, headers=headers, json={"ok": status == 200})

    return httpx.MockTransport(handler), calls


def test_success_on_first_try_makes_one_call_and_never_sleeps():
    transport, calls = _responses_transport([200])
    client = httpx.Client(transport=transport)
    sleeps = []

    response = http.get("https://api.example.com/jobs", client=client, sleep=sleeps.append)

    assert response.status_code == 200
    assert calls["count"] == 1
    assert sleeps == []


def test_retries_on_429_then_succeeds_within_the_cap():
    transport, calls = _responses_transport([429, 429, 200])
    client = httpx.Client(transport=transport)
    sleeps = []

    response = http.get(
        "https://api.example.com/jobs",
        client=client,
        max_retries=3,
        backoff_base=1.0,
        sleep=sleeps.append,
    )

    assert response.status_code == 200
    assert calls["count"] == 3
    assert len(sleeps) == 2


def test_exponential_backoff_without_retry_after_header():
    transport, calls = _responses_transport([429, 429, 429, 200])
    client = httpx.Client(transport=transport)
    sleeps = []

    http.get(
        "https://api.example.com/jobs",
        client=client,
        max_retries=3,
        backoff_base=1.0,
        sleep=sleeps.append,
    )

    assert sleeps == [1.0, 2.0, 4.0]


def test_retry_after_header_is_honored_over_exponential_backoff():
    transport, calls = _responses_transport(
        [429, 200], headers_by_call={0: {"Retry-After": "7"}}
    )
    client = httpx.Client(transport=transport)
    sleeps = []

    http.get(
        "https://api.example.com/jobs",
        client=client,
        max_retries=3,
        backoff_base=1.0,
        sleep=sleeps.append,
    )

    assert sleeps == [7.0]


def test_gives_up_after_the_retry_cap_and_raises():
    transport, calls = _responses_transport([429, 429, 429, 429])
    client = httpx.Client(transport=transport)
    sleeps = []

    with pytest.raises(http.RateLimitExceeded):
        http.get(
            "https://api.example.com/jobs",
            client=client,
            max_retries=3,
            backoff_base=1.0,
            sleep=sleeps.append,
        )

    # initial attempt + max_retries retries = 4 calls total, then gives up.
    assert calls["count"] == 4
