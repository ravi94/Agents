"""T007 [Foundational] — unit tests for the file-based response cache.

Covers a hit within the TTL being served without a re-fetch, a miss/expired
entry being reported as absent, and cache keys being stable per
``(source, endpoint, params)``. Written first (Constitution VII) — expected to
fail until T008 implements `jobhunter.sources.cache`.
"""

from jobhunter.sources import cache


def test_miss_returns_none(tmp_path):
    result = cache.get("jsearch", "search", {"query": "Backend Engineer"}, cache_dir=tmp_path)
    assert result is None


def test_hit_within_ttl_is_served_without_a_call(tmp_path):
    params = {"query": "Backend Engineer", "page": 1}
    cache.set("jsearch", "search", params, {"data": ["posting"]}, cache_dir=tmp_path, now=lambda: 1000.0)

    result = cache.get(
        "jsearch", "search", params, cache_dir=tmp_path, ttl_seconds=6 * 3600, now=lambda: 1000.0 + 60
    )

    assert result == {"data": ["posting"]}


def test_expired_entry_is_a_miss(tmp_path):
    params = {"query": "Backend Engineer", "page": 1}
    cache.set("jsearch", "search", params, {"data": ["posting"]}, cache_dir=tmp_path, now=lambda: 1000.0)

    result = cache.get(
        "jsearch",
        "search",
        params,
        cache_dir=tmp_path,
        ttl_seconds=6 * 3600,
        now=lambda: 1000.0 + 6 * 3600 + 1,
    )

    assert result is None


def test_keys_are_stable_for_identical_inputs(tmp_path):
    params = {"query": "Backend Engineer", "page": 1}
    cache.set("jsearch", "search", params, {"data": ["a"]}, cache_dir=tmp_path, now=lambda: 1000.0)

    # Re-derived params dict (different object, same content/order-independent).
    same_params = {"page": 1, "query": "Backend Engineer"}
    result = cache.get("jsearch", "search", same_params, cache_dir=tmp_path, now=lambda: 1000.0 + 1)

    assert result == {"data": ["a"]}


def test_keys_differ_for_different_source_endpoint_or_params(tmp_path):
    params = {"query": "Backend Engineer"}
    cache.set("jsearch", "search", params, {"data": ["a"]}, cache_dir=tmp_path, now=lambda: 1000.0)

    assert cache.get("adzuna", "search", params, cache_dir=tmp_path, now=lambda: 1000.0) is None
    assert cache.get("jsearch", "details", params, cache_dir=tmp_path, now=lambda: 1000.0) is None
    assert (
        cache.get(
            "jsearch", "search", {"query": "Other Role"}, cache_dir=tmp_path, now=lambda: 1000.0
        )
        is None
    )
