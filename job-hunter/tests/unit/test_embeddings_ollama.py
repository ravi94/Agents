"""T006 [P] [Foundational] — unit tests for the local Ollama embeddings client.

`embed(text)` is the one seam scoring's `scope` component depends on
(research.md §2): a mocked successful HTTP response returns the embedding
vector; a connection error or timeout returns `None` rather than raising, so
callers (scorer.py) have a clean fallback signal instead of a crashed run.
Written first (Constitution VII) — expected to fail until T007 implements
`jobhunter.embeddings.ollama`. No live Ollama call is ever a pass condition.
"""

from __future__ import annotations

import json

import httpx
import pytest

from jobhunter.embeddings import ollama


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_embed_returns_vector_on_successful_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embeddings"
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    vector = ollama.embed("senior backend engineer", client=_mock_client(handler))

    assert vector == [0.1, 0.2, 0.3]


def test_embed_sends_the_configured_model_and_prompt():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"embedding": [0.5]})

    ollama.embed("payments platform", client=_mock_client(handler))

    assert captured["body"]["model"] == ollama.EMBEDDING_MODEL
    assert captured["body"]["prompt"] == "payments platform"


def test_embed_returns_none_on_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    vector = ollama.embed("senior backend engineer", client=_mock_client(handler))

    assert vector is None


def test_embed_returns_none_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    vector = ollama.embed("senior backend engineer", client=_mock_client(handler))

    assert vector is None


def test_embed_returns_none_on_non_200_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model not loaded"})

    vector = ollama.embed("senior backend engineer", client=_mock_client(handler))

    assert vector is None


def test_embed_returns_none_on_malformed_response_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    vector = ollama.embed("senior backend engineer", client=_mock_client(handler))

    assert vector is None


def test_embed_never_raises_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    try:
        result = ollama.embed("senior backend engineer", client=_mock_client(handler))
    except Exception as exc:  # noqa: BLE001 - the point of the test is that this never fires
        pytest.fail(f"embed() must never raise, got {exc!r}")
    else:
        assert result is None
