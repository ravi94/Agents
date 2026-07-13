"""T012 [US1] — the hard-filter gate every job crosses before scoring.

The executable form of contracts/scoring_algorithm.md "Hard filters": each
`state='new'` job is checked against the five non-negotiable dimensions
(`locations`, `work_modes`, `company_types`, `comp_floor_lpa`,
`seniority_floor`) and reduced to a :class:`FilterResult`. Missing data for a
dimension is *pass-through*, not a failure (FR-003) — a floor is only enforced
when there is a value to compare. `failed_filters` collects **every** violated
dimension, not just the first, so the eventual
`reason="failed: <comma-joined dimensions>"` is complete.

Company type and seniority are inferred from free text here (the source dicts
carry no structured field for either); that inference is deliberately internal
— tests assert only the resulting :class:`FilterResult`, never how it was
derived.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Seniority

# Fixed seniority order (contracts/scoring_algorithm.md): a job passes the
# floor when its inferred rank is >= the configured floor's rank.
_SENIORITY_ORDER: tuple[Seniority, ...] = ("junior", "mid", "senior", "staff", "principal")
_SENIORITY_RANK: dict[str, int] = {name: rank for rank, name in enumerate(_SENIORITY_ORDER)}

# Title keywords mapped to a seniority level, checked high-to-low so a
# "Senior Staff Engineer" resolves to the more specific higher rank.
_SENIORITY_KEYWORDS: tuple[tuple[Seniority, tuple[str, ...]], ...] = (
    ("principal", ("principal",)),
    ("staff", ("staff",)),
    ("senior", ("senior", "sr.", "sr ", "lead")),
    ("mid", ("mid-level", "mid level", "midlevel", "intermediate")),
    ("junior", ("junior", "jr.", "jr ", "entry-level", "entry level", "graduate", "intern")),
)

# Company-type keywords, checked in priority order: a "staffing agency placing
# contractors with enterprise clients" must classify as staffing_agency, not
# enterprise, so staffing wins over the enterprise/startup signals it may also
# mention.
_COMPANY_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("staffing_agency", ("staffing", "recruitment agency", "recruiting agency", "recruitment firm", "consultancy", "consulting firm")),
    ("startup", ("startup", "start-up", "series a", "series b", "series c", "series d", "seed-stage", "seed stage", "early-stage", "early stage", "pre-seed")),
    ("enterprise", ("fortune 500", "fortune 100", "multinational", "conglomerate", "publicly traded", "public company", "enterprise")),
    ("midsize", ("mid-size", "midsize", "mid-sized", "scale-up", "scaleup", "growth-stage", "growth stage")),
)


@dataclass(frozen=True)
class FilterResult:
    """Outcome of the hard-filter gate for one job.

    `passed` is `True` only when every dimension passes; otherwise
    `failed_filters` names each violated dimension (in the fixed dimension
    order) and is written into the job's `reason`.
    """

    passed: bool
    failed_filters: list[str] = field(default_factory=list)


def apply_filters(job: dict, prefs: Preferences) -> FilterResult:
    """Gate one job against every hard filter, collecting all violations.

    Each dimension is evaluated independently — a job failing several reports
    all of them — and any dimension whose data is absent passes through rather
    than counting as a failure (FR-003). A job that clears every dimension is
    `passed=True` with an empty `failed_filters`.
    """
    hard = prefs.hard_filters
    failed: list[str] = []

    if not _passes_locations(job, hard.locations):
        failed.append("locations")
    if not _passes_work_modes(job, hard.work_modes):
        failed.append("work_modes")
    if not _passes_company_types(job, hard.company_types_allow, hard.company_types_deny):
        failed.append("company_types")
    if not _passes_comp_floor(job, hard.comp_floor_lpa):
        failed.append("comp_floor_lpa")
    if not _passes_seniority_floor(job, hard.seniority_floor):
        failed.append("seniority_floor")

    return FilterResult(passed=not failed, failed_filters=failed)


def _passes_locations(job: dict, allowed: list[str]) -> bool:
    """Pass when the job is remote or its city/location matches an allowed one.

    Matching is case-insensitive and substring-based (an allowed "Bangalore"
    matches a `location` of "Bangalore, India"). A remote job always passes
    regardless of city, per the contract table.
    """
    if job.get("work_mode") == "remote":
        return True

    haystack = f"{job.get('city') or ''} {job.get('location') or ''}".lower()
    return any(loc.lower() in haystack for loc in allowed)


def _passes_work_modes(job: dict, allowed: list[str]) -> bool:
    """Pass when the work mode is allowed, or `"unknown"` (pass-through, FR-003)."""
    work_mode = job.get("work_mode")
    if work_mode == "unknown" or work_mode is None:
        return True
    return work_mode in allowed


def _passes_company_types(job: dict, allow: list[str], deny: list[str]) -> bool:
    """Pass unless the inferred company type is denied or outside a non-empty allow list.

    An undeterminable company type passes both checks — a proxy signal is never
    treated as a hard failure when it could not be read at all.
    """
    company_type = _infer_company_type(job)
    if company_type is None:
        return True
    if deny and company_type in deny:
        return False
    if allow and company_type not in allow:
        return False
    return True


def _passes_comp_floor(job: dict, floor_lpa: float) -> bool:
    """Pass when the parsed salary (LPA) meets the floor, or when none is listed.

    No listed salary is pass-through (FR-003): the comp floor is enforced only
    when there is a number to compare.
    """
    salary_lpa = _parse_lpa(job.get("salary"))
    if salary_lpa is None:
        return True
    return salary_lpa >= floor_lpa


def _passes_seniority_floor(job: dict, floor: Seniority) -> bool:
    """Pass when inferred seniority meets the floor, or is undeterminable.

    A title carrying no seniority word passes through rather than failing —
    an unread proxy is never a hard violation.
    """
    seniority = _infer_seniority(job.get("title"))
    if seniority is None:
        return True
    return _SENIORITY_RANK[seniority] >= _SENIORITY_RANK[floor]


def _infer_company_type(job: dict) -> str | None:
    """Infer a company type from the company name + description, or `None`.

    Priority order (staffing_agency first) resolves texts that mention several
    signals to the most specific one.
    """
    text = f"{job.get('company') or ''} {job.get('description') or ''}".lower()
    for company_type, keywords in _COMPANY_TYPE_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return company_type
    return None


def _infer_seniority(title: str | None) -> Seniority | None:
    """Infer a seniority level from the job title, or `None` if it carries no cue."""
    if not title:
        return None
    lowered = title.lower()
    for level, keywords in _SENIORITY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return level
    return None


def _parse_lpa(salary: str | None) -> float | None:
    """Parse a salary string to an LPA float, or `None` when there is no number.

    Handles the "45 LPA" / "12 LPA" form the M2 normalizer and fixtures use
    (and range forms like "45-60 LPA", taking the lower bound as the floor
    comparison value). A blank/absent salary — or one with no parseable number
    — is missing data and returns `None` for pass-through.
    """
    if not salary:
        return None
    numbers = re.findall(r"\d+(?:\.\d+)?", salary)
    if not numbers:
        return None
    return min(float(n) for n in numbers)
