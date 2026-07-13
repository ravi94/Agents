"""T007 [Foundational] — local Ollama embeddings client for scoring's `scope` component.

Calls Ollama's local REST API (`/api/embeddings`, `mxbai-embed-large`) via the
already-declared `httpx` dependency (Constitution I: embeddings always run
locally via Ollama). Bounded timeout; any failure — connection error, timeout,
non-200 response, or a malformed response body — collapses to `None` rather
than raising, so `scoring/scorer.py` has one clean fallback signal instead of
a crashed run (research.md §2).
"""

from __future__ import annotations

import httpx

DEFAULT_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "mxbai-embed-large"
DEFAULT_TIMEOUT = 10.0


def embed(
    text: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    model: str = EMBEDDING_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.Client | None = None,
) -> list[float] | None:
    """Return the embedding vector for ``text``, or ``None`` on any failure.

    Never raises: a connection error, timeout, non-200 response, or malformed
    response body all collapse to ``None`` so callers get one clean fallback
    signal instead of needing to catch multiple exception types.
    """
    owns_client = client is None
    http_client = client or httpx.Client(timeout=timeout)
    try:
        response = http_client.post(
            f"{base_url}/api/embeddings",
            json={"model": model, "prompt": text},
        )
    except httpx.HTTPError:
        return None
    finally:
        if owns_client:
            http_client.close()

    if response.status_code != 200:
        return None

    try:
        embedding = response.json()["embedding"]
    except (ValueError, KeyError, TypeError):
        return None

    if not isinstance(embedding, list):
        return None
    return embedding
