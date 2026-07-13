"""T018 [US1] — idempotency key computation and within-run dedup.

Implements the id contract of Constitution IV: a stable source id wins when
the source guarantees it, otherwise postings collapse to a normalized
``title|company|city`` composite so duplicates from different sources — which
have no shared source id — can still be recognized as the same posting.
"""

from __future__ import annotations

import re

_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize_segment(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE_RUN.sub(" ", value.strip().lower())


def compute_id(
    *,
    source: str,
    source_id: str | None,
    id_is_stable: bool,
    title: str | None,
    company: str | None,
    city: str | None,
) -> str | None:
    """Return the posting's idempotency key, or ``None`` if none is usable."""
    if id_is_stable and source_id:
        return f"{source}:{source_id}"

    norm_title = _normalize_segment(title)
    norm_company = _normalize_segment(company)
    norm_city = _normalize_segment(city)

    if not norm_title and not norm_company:
        return None

    segments = [segment for segment in (norm_title, norm_company, norm_city) if segment]
    return "|".join(segments)


def dedup_within_run(jobs: list[dict]) -> list[dict]:
    """Collapse duplicate ids in one batch, keeping the richer payload."""
    best_by_id: dict = {}
    order: list = []

    for job in jobs:
        job_id = job.get("id")
        if not job_id:
            continue

        if job_id not in best_by_id:
            best_by_id[job_id] = job
            order.append(job_id)
            continue

        current = best_by_id[job_id]
        current_richness = sum(1 for v in current.values() if v is not None)
        candidate_richness = sum(1 for v in job.values() if v is not None)
        if candidate_richness > current_richness:
            best_by_id[job_id] = job

    return [best_by_id[job_id] for job_id in order]
