"""T002 [Setup] — shared `JobSource` test doubles for the pipeline tests.

Two fixtures let the orchestration tests exercise the discover→score path and
the per-source failure path with no live network (contracts/pipeline.md,
research.md §9):

- `FakeJobSource` returns a fixed set of raw postings and records the queries
  it was handed, so a test can drive the whole pipeline off deterministic data.
- `FailingJobSource` always raises `SourceError`, so a test can prove one dead
  source is isolated (recorded in `RunSummary.source_failures`) while the
  healthy sources still flow through to scoring (FR-004, US2).

`make_jsearch_posting` builds a minimal JSearch-shaped posting that
`normalize_jsearch` accepts, so tests need no large fixture file to produce a
new, normalizable role.
"""

from __future__ import annotations

from jobhunter.sources.base import RawPosting, SearchQuery, SourceError


class FakeJobSource:
    """A `JobSource` stand-in that returns fixture postings, no network I/O."""

    def __init__(self, postings: list[RawPosting], *, name: str = "jsearch"):
        self.name = name
        self._postings = postings
        self.received_queries: list[SearchQuery] = []

    def fetch(self, queries: list[SearchQuery]) -> list[RawPosting]:
        self.received_queries = list(queries)
        return self._postings


class FailingJobSource:
    """A `JobSource` stand-in whose `fetch` always raises `SourceError`."""

    def __init__(self, *, name: str = "adzuna", reason: str = "boom"):
        self.name = name
        self._reason = reason
        self.received_queries: list[SearchQuery] = []

    def fetch(self, queries: list[SearchQuery]) -> list[RawPosting]:
        self.received_queries = list(queries)
        raise SourceError(self._reason)


def make_jsearch_posting(
    *,
    title: str = "Staff Backend Engineer",
    company: str = "Northwind Systems",
    city: str = "Bangalore",
    description: str = "Remote-friendly Python distributed systems role.",
    min_salary: int | None = 4_000_000,
    max_salary: int | None = 6_000_000,
) -> RawPosting:
    """A minimal JSearch-shaped raw posting that `normalize_jsearch` accepts."""
    return {
        "job_title": title,
        "employer_name": company,
        "job_city": city,
        "job_location": f"{city}, India",
        "job_country": "IN",
        "job_description": description,
        "job_is_remote": True,
        "job_employment_type": "FULLTIME",
        "job_min_salary": min_salary,
        "job_max_salary": max_salary,
        "job_salary_period": "YEAR",
        "job_apply_link": "https://example.test/apply",
    }
