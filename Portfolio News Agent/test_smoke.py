"""Dependency-light smoke tests. Run: .venv/bin/python test_smoke.py

Mocks the LLM and tools so nothing hits Ollama or the network. Verifies the wiring:
config, both tool-calling modes, the agent loop, guardrails, brief rendering, dry-run.
Exits non-zero on first failure.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from portfolio_news_agent import agent_loop, brief, run as run_mod
from portfolio_news_agent.config import Config, Holding
from portfolio_news_agent.llm_client import LLMClient, LLMResponse, ToolCall
from portfolio_news_agent.prompts import build_holdings_block
from portfolio_news_agent.tools.registry import TOOL_SCHEMAS

logging.basicConfig(level=logging.WARNING)


def _cfg(**over) -> Config:
    base = dict(
        ollama_base_url="http://x/v1", model_name="m", tool_mode="auto",
        search_provider="searxng", serpapi_api_key="",
        searxng_url="http://localhost:8080", searxng_rate_limit_rps=1.0,
        searxng_rate_limit_burst=3, searxng_max_retries=4,
        searxng_backoff_base=1.0, searxng_backoff_max=30.0, searxng_timeout=15.0,
        search_cache_enabled=False, search_cache_dir=Path("."),
        max_iterations=8,
        max_tool_calls=20, run_timeout_seconds=300, fetch_char_budget=8000,
        delivery_mode="email", output_dir=Path("."),
        smtp_host="", smtp_port=587, smtp_username="", smtp_password="",
        email_from="", email_to="", holdings=[Holding("AAPL", "Apple")],
    )
    base.update(over)
    return Config(**base)


def test_brief_render():
    b = "AAPL: beats. https://news.example/aapl"
    html = brief.to_html(b)
    assert '<a href="https://news.example/aapl">' in html, "URL not linkified"
    assert "AAPL" in html and "<p>" in html
    assert brief.to_plaintext(b).endswith("\n")
    assert "Portfolio Brief —" in brief.subject()


def test_prompt_block():
    blk = build_holdings_block([Holding("AAPL", "Apple", "watch services")])
    assert "AAPL (Apple) — note: watch services" in blk
    assert "Today is" in blk


def test_tool_schemas():
    assert {t["function"]["name"] for t in TOOL_SCHEMAS} == {"web_search", "web_fetch"}


def test_prompt_mode_parsing():
    """A model that ignores `tools` and emits JSON in content still yields a ToolCall."""
    client = LLMClient("http://x/v1", "m", tool_mode="prompt")
    fake = {
        "choices": [
            {"message": {"content": '{"tool_call": {"name": "web_search", "arguments": {"query": "AAPL news"}}}'}}
        ]
    }
    with patch("portfolio_news_agent.llm_client.requests.post") as post:
        post.return_value = MagicMock(json=lambda: fake, raise_for_status=lambda: None)
        resp = client.chat([{"role": "system", "content": "x"}], TOOL_SCHEMAS)
    assert resp.wants_tools, "prompt-mode tool call not parsed"
    assert resp.tool_calls[0].name == "web_search"
    assert resp.tool_calls[0].arguments == {"query": "AAPL news"}


def test_prompt_mode_final_prose():
    """Prose with no JSON in prompt mode is treated as the final brief."""
    client = LLMClient("http://x/v1", "m", tool_mode="prompt")
    fake = {"choices": [{"message": {"content": "AAPL: no material news today."}}]}
    with patch("portfolio_news_agent.llm_client.requests.post") as post:
        post.return_value = MagicMock(json=lambda: fake, raise_for_status=lambda: None)
        resp = client.chat([{"role": "system", "content": "x"}], TOOL_SCHEMAS)
    assert not resp.wants_tools
    assert "no material news" in resp.content


def _scripted_loop(cfg, turns):
    seq = iter(turns)
    with patch("portfolio_news_agent.agent_loop.LLMClient") as LC, \
         patch("portfolio_news_agent.tools.registry.get_provider") as GP, \
         patch("portfolio_news_agent.tools.web_fetch.fetch", return_value="article text..."):
        LC.return_value.chat.side_effect = lambda *a, **k: next(seq)
        prov = MagicMock()
        prov.search.return_value = [
            type("R", (), {"title": "t", "url": "https://news.example/aapl", "snippet": "s"})()
        ]
        GP.return_value = prov
        return agent_loop.run_agent(cfg)


def test_agent_loop_full():
    turns = [
        LLMResponse("", [ToolCall("c1", "web_search", {"query": "AAPL news"})]),
        LLMResponse("", [ToolCall("c2", "web_fetch", {"url": "https://news.example/aapl"})]),
        LLMResponse("AAPL: Apple beats Q3 earnings. https://news.example/aapl", []),
    ]
    result = _scripted_loop(_cfg(), turns)
    assert "Apple beats Q3 earnings" in result


def test_max_tool_calls_guardrail():
    """When the model keeps calling tools, the cap forces a final summary."""
    spam = LLMResponse("", [ToolCall("c", "web_search", {"query": "x"})])
    forced = LLMResponse("forced final brief", [])
    # max_tool_calls=2: two tool turns, then _force_final returns `forced`.
    turns = [spam, spam, forced]
    result = _scripted_loop(_cfg(max_tool_calls=2), turns)
    assert result == "forced final brief"


def test_search_cache_dedupes(tmp_path=None):
    """Second identical search is served from cache; the provider is hit only once."""
    import tempfile
    from portfolio_news_agent.tools.registry import ToolDispatcher

    with tempfile.TemporaryDirectory() as d:
        cfg = _cfg(search_cache_enabled=True, search_cache_dir=Path(d))
        with patch("portfolio_news_agent.tools.registry.get_provider") as GP:
            prov = MagicMock()
            prov.search.return_value = [
                type("R", (), {"title": "t", "url": "https://x/1", "snippet": "s"})()
            ]
            GP.return_value = prov
            disp = ToolDispatcher(cfg)
            r1 = disp.dispatch("web_search", {"query": "AAPL news", "max_results": 5})
            r2 = disp.dispatch("web_search", {"query": "aapl news", "max_results": 5})
    assert r1 == r2, "cache returned different payload"
    assert prov.search.call_count == 1, "provider hit twice; cache miss"


def test_search_cache_skips_empty():
    """Empty (likely throttled) results are not cached, so they can be retried."""
    import tempfile
    from portfolio_news_agent.tools.search.cache import SearchCache

    with tempfile.TemporaryDirectory() as d:
        c = SearchCache(Path(d), "searxng", enabled=True)
        c.put("q", 5, [])
        assert c.get("q", 5) is None, "empty result should not be cached"
        c.put("q", 5, [{"title": "t", "url": "u", "snippet": "s"}])
        assert c.get("q", 5) is not None, "non-empty result should be cached"


def test_searxng_parses_json_results():
    """A normal JSON payload is mapped to SearchResult(title, url, snippet)."""
    from portfolio_news_agent.tools.search.searxng import SearxngProvider

    prov = SearxngProvider("http://localhost:8080", rate_limit_rps=1000.0)
    payload = {"results": [
        {"title": "T1", "url": "https://a/1", "content": "snippet one"},
        {"title": "T2", "url": "https://a/2", "content": "snippet two"},
    ]}
    resp = MagicMock(status_code=200, json=lambda: payload,
                     raise_for_status=lambda: None)
    with patch.object(prov._session, "request", return_value=resp):
        results = prov.search("anything", max_results=5)
    assert [r.url for r in results] == ["https://a/1", "https://a/2"]
    assert results[0].title == "T1" and results[0].snippet == "snippet one"


def test_searxng_rate_limited_yields_empty():
    """Exhausted 429 retries => [] (not a raise) and throttled_count is bumped."""
    from portfolio_news_agent.tools.search.searxng import SearxngProvider

    prov = SearxngProvider("http://localhost:8080", rate_limit_rps=1000.0,
                           max_retries=0, backoff_base=0.0, backoff_max=0.0)
    resp = MagicMock(status_code=429, headers={}, raise_for_status=lambda: None)
    with patch.object(prov._session, "request", return_value=resp):
        results = prov.search("anything")
    assert results == [], "rate-limited search should yield no results"
    assert prov.throttled_count == 1


def _scripted_loop_empty_search(cfg, turns, throttled=False):
    """Like _scripted_loop but the provider returns NO results (simulating throttle)."""
    seq = iter(turns)
    with patch("portfolio_news_agent.agent_loop.LLMClient") as LC, \
         patch("portfolio_news_agent.tools.registry.get_provider") as GP, \
         patch("portfolio_news_agent.tools.web_fetch.fetch", return_value="article text..."):
        LC.return_value.chat.side_effect = lambda *a, **k: next(seq)
        prov = MagicMock()
        prov.search.return_value = []  # nothing came back
        prov.throttled_count = 1 if throttled else 0
        GP.return_value = prov
        return agent_loop.run_agent(cfg)


def test_guard_replaces_hallucinated_brief_when_throttled():
    """All searches empty + throttled => model's brief is discarded for an honest message."""
    turns = [
        LLMResponse("", [ToolCall("c1", "web_search", {"query": "BEL news"})]),
        # Model fabricates a brief despite the empty search result:
        LLMResponse("BEL: Big fake merger! https://fake.example/x", []),
    ]
    result = _scripted_loop_empty_search(_cfg(), turns, throttled=True)
    assert "fake" not in result.lower(), "hallucinated brief was not replaced"
    assert "rate-limited" in result.lower() or "throttled" in result.lower()


def test_guard_allows_brief_when_grounded():
    """If at least one search returns results, the model's brief is trusted as-is."""
    turns = [
        LLMResponse("", [ToolCall("c1", "web_search", {"query": "AAPL news"})]),
        LLMResponse("AAPL: Apple beats Q3 earnings. https://news.example/aapl", []),
    ]
    result = _scripted_loop(_cfg(), turns)  # _scripted_loop returns 1 result per search
    assert "Apple beats Q3 earnings" in result, "grounded brief should pass through"


def test_dry_run_exit_code():
    turns = [LLMResponse("AAPL: no material news today.", [])]
    seq = iter(turns)
    with patch("portfolio_news_agent.run.load_config", return_value=_cfg()), \
         patch("portfolio_news_agent.agent_loop.LLMClient") as LC, \
         patch("portfolio_news_agent.tools.registry.get_provider", return_value=MagicMock()):
        LC.return_value.chat.side_effect = lambda *a, **k: next(seq)
        rc = run_mod.main(["--dry-run"])
    assert rc == 0


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
