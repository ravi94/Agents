"""T019 [US2] — unit tests for the JSearch (RapidAPI) source adapter.

Covers a successful fetch flattening the fixture's ``data`` list, the missing-
credential short-circuit (no request attempted), a cache hit served without a
call, the per-run query budget being respected, and a persistent 429 being
translated into ``SourceError`` rather than escaping raw. Written first
(Constitution VII) — expected to fail until T019 implements
``jobhunter.sources.jsearch``.
"""

import json
from pathlib import Path

import httpx
import pytest

from jobhunter import http
from jobhunter.sources import cache
from jobhunter.sources.base import SearchQuery, SourceError
from jobhunter.sources.jsearch import JSearchSource

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "jsearch_response.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())


def _transport(json_body, status_code=200):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(status_code, json=json_body)

    return httpx.MockTransport(handler), calls


def _always_429_transport():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(429, json={"message": "rate limited"})

    return httpx.MockTransport(handler), calls


def test_fetch_returns_flattened_data_for_one_query(tmp_path):
    transport, calls = _transport(FIXTURE)
    client = httpx.Client(transport=transport)
    source = JSearchSource(api_key="test-key", client=client, cache_dir=tmp_path)

    result = source.fetch([SearchQuery(keywords="Backend Engineer", location="Bangalore, India")])

    assert result == FIXTURE["data"]["jobs"]
    assert calls["count"] == 1


def test_missing_api_key_raises_without_any_request(tmp_path, monkeypatch):
    monkeypatch.delenv("JSEARCH_API_KEY", raising=False)
    transport, calls = _transport(FIXTURE)
    client = httpx.Client(transport=transport)
    source = JSearchSource(client=client, cache_dir=tmp_path)

    with pytest.raises(SourceError):
        source.fetch([SearchQuery(keywords="Backend Engineer", location="Bangalore, India")])

    assert calls["count"] == 0


def test_cache_hit_is_served_without_calling_the_transport(tmp_path):
    query = SearchQuery(keywords="Backend Engineer", location="Bangalore, India")
    params = {
        "query": f"{query.keywords} in {query.location}",
        "page": 1,
        "num_pages": 1,
    }
    cache.set("jsearch", "search", params, FIXTURE, cache_dir=tmp_path)

    transport, calls = _transport(FIXTURE)
    client = httpx.Client(transport=transport)
    source = JSearchSource(api_key="test-key", client=client, cache_dir=tmp_path)

    result = source.fetch([query])

    assert result == FIXTURE["data"]["jobs"]
    assert calls["count"] == 0


def test_budget_bounds_the_number_of_requests(tmp_path):
    transport, calls = _transport({"status": "OK", "parameters": {}, "data": {"jobs": []}})
    client = httpx.Client(transport=transport)
    source = JSearchSource(api_key="test-key", budget=2, client=client, cache_dir=tmp_path)

    queries = [
        SearchQuery(keywords="Backend Engineer", location="Bangalore, India"),
        SearchQuery(keywords="Platform Engineer", location="Pune, India"),
        SearchQuery(keywords="Staff Engineer", location="Hyderabad, India"),
        SearchQuery(keywords="Data Engineer", location="Chennai, India"),
    ]

    source.fetch(queries)

    assert calls["count"] == 2


def test_persistent_rate_limit_becomes_a_source_error(tmp_path, monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda *_: None)
    transport, calls = _always_429_transport()
    client = httpx.Client(transport=transport)
    source = JSearchSource(api_key="test-key", client=client, cache_dir=tmp_path)

    with pytest.raises(SourceError):
        source.fetch([SearchQuery(keywords="Backend Engineer", location="Bangalore, India")])

    assert calls["count"] > 1
