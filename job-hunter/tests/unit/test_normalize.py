"""T010 [US1] — unit tests for JSearch normalization (discovery/normalize.py).

`jsearch_response.json` maps to canonical `Job` fields per
contracts/source_mapping.md: absent optional fields (salary, etc.) are null —
never fabricated (FR-010); a posting missing title+company is skipped, i.e.
`normalize_jsearch` returns `None` (FR-011). Written first (Constitution VII)
— expected to fail until T016 (work-mode helper) and T017 (JSearch
normalization) land.
"""

from __future__ import annotations

import json
from pathlib import Path

from jobhunter.discovery.normalize import normalize_jsearch

FIXTURE = Path(__file__).parent.parent / "fixtures" / "jsearch_response.json"


def _postings() -> list[dict]:
    return json.loads(FIXTURE.read_text())["data"]["jobs"]


def test_maps_required_and_explicit_remote_fields():
    posting = _postings()[0]  # Staff Backend Engineer, job_is_remote=true

    job = normalize_jsearch(posting)

    assert job is not None
    assert job["source"] == "jsearch"
    assert job["title"] == "Staff Backend Engineer"
    assert job["company"] == "Northwind Systems"
    assert job["location"] == "Bangalore, Karnataka, India"
    assert job["city"] == "Bangalore"
    assert job["country"] == "IN"
    assert job["work_mode"] == "remote"
    assert job["employment_type"] == "FULLTIME"
    assert job["description"] == posting["job_description"]
    assert job["apply_url"] == "https://jobs.example.com/apply/0001"
    # JSearch job_id is aggregate-derived (not stable) → fallback composite,
    # lowercased/trimmed, no source prefix (contracts/source_mapping.md).
    assert job["id"] == "staff backend engineer|northwind systems|bangalore"


def test_absent_optional_fields_are_null_never_fabricated():
    posting = _postings()[0]  # job_min_salary / job_max_salary both null

    job = normalize_jsearch(posting)

    assert job["salary"] is None


def test_salary_is_rendered_when_present():
    posting = _postings()[1]  # min 2500000, max 3800000, period YEAR

    job = normalize_jsearch(posting)

    assert job["salary"] is not None
    assert "2500000" in job["salary"]
    assert "3800000" in job["salary"]
    assert "YEAR" in job["salary"]


def test_text_inferred_work_mode_when_not_explicitly_remote():
    posting = _postings()[1]  # job_is_remote=false, description mentions "Hybrid"

    job = normalize_jsearch(posting)

    assert job["work_mode"] == "hybrid"


def test_missing_city_is_left_empty_not_fabricated():
    posting = _postings()[3]  # job_city == ""

    job = normalize_jsearch(posting)

    assert job["city"] == ""
    # Composite falls back to title|company when city is missing.
    assert job["id"] == "backend engineer|cascade analytics"


def test_posting_missing_title_and_company_is_skipped():
    posting = _postings()[4]  # job_title and employer_name both null

    assert normalize_jsearch(posting) is None
