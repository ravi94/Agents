"""T004 [Foundational] — the ``JobSource`` interface and its pipeline types.

The swap seam that lets a new source (the ATS watchlist, later) join discovery
without changing the orchestrator (FR-002, Constitution VI). A source only
needs a stable ``name`` and a ``fetch`` that turns ``SearchQuery`` objects into
raw, source-shaped ``RawPosting`` dicts — mapping to the canonical ``Job`` is
the per-source normalizer's job, not the source's (contracts/job_source.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# A source-shaped posting dict, opaque to the orchestrator; only the
# per-source normalizer in discovery/normalize.py interprets its keys.
RawPosting = dict[str, Any]


@dataclass(frozen=True)
class SearchQuery:
    """One source lookup: a role/keyword term paired with a location."""

    keywords: str
    location: str


class SourceError(Exception):
    """Raised by a ``JobSource.fetch`` on an unrecoverable failure.

    Covers network errors, auth failures, rate-limiting after bounded retries,
    a malformed response, or a missing required credential. The orchestrator
    catches this per source, records the failure, and continues with the
    others (FR-017) — a source must never let this escape as a bare exception
    or call ``sys.exit`` itself.
    """


@runtime_checkable
class JobSource(Protocol):
    """The pluggable seam every discovery source implements.

    ``name`` MUST be a stable, lowercase, unique source identity (``"jsearch"``,
    ``"adzuna"``, later ``"ats"``) — it is used as the ``source`` column value,
    the trace ``source=`` tag, and the summary key.
    """

    name: str

    def fetch(self, queries: list[SearchQuery]) -> list[RawPosting]:
        """Issue this source's lookups and return raw, source-shaped postings.

        MUST respect the per-source query budget, route all HTTP through the
        shared ``http.py`` wrapper (caching + 429 backoff), and raise
        ``SourceError`` — never crash the process — on an unrecoverable
        failure or a missing required credential.
        """
        ...
