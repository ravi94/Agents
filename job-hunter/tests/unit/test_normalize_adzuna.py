"""T028 [P] [US3] — unit tests for Adzuna normalization (discovery/normalize.py).

`adzuna_response.json` maps to canonical `Job` fields per
contracts/source_mapping.md: work mode is text-inferred (Adzuna has no
explicit remote flag, unlike JSearch); the stable Adzuna `id` is used
(`"adzuna:<source_id>"`) while a normalized `title|company|city` composite is
additionally recorded as `dedup_key` so the same role posted on JSearch can
still be recognized as a duplicate later (cross-source collapse, T029/T033).
Written first (Constitution VII) — expected to fail until T031 (Adzuna
adapter, unrelated to this test) and T032 (`normalize_adzuna`) land.
"""

from __future__ import annotations

import json
from pathlib import Path

from jobhunter.discovery.normalize import normalize_adzuna

FIXTURE = Path(__file__).parent.parent / "fixtures" / "adzuna_response.json"


def _postings() -> list[dict]:
    return json.loads(FIXTURE.read_text())["results"]


def test_maps_required_fields_and_text_infers_remote():
    posting = _postings()[0]  # Backend Engineer, Distributed Systems — no explicit remote flag

    job = normalize_adzuna(posting)

    assert job is not None
    assert job["source"] == "adzuna"
    assert job["title"] == "Backend Engineer, Distributed Systems"
    assert job["company"] == "Meridian Cloud"
    assert job["location"] == "Bangalore, Karnataka"
    assert job["description"] == posting["description"]
    assert job["apply_url"] == "https://www.adzuna.in/land/ad/4021557831"
    # "remote-friendly" / "Work from home" in the description, no explicit flag.
    assert job["work_mode"] == "remote"


def test_city_and_country_parsed_from_area_hierarchy():
    posting = _postings()[0]

    job = normalize_adzuna(posting)

    assert job["city"] == "Bangalore"
    assert job["country"] == "India"


def test_short_area_leaves_city_empty_not_fabricated():
    posting = _postings()[2]  # Platform Engineer — area == ["India"], no city level

    job = normalize_adzuna(posting)

    assert job["country"] == "India"
    assert job["city"] == ""
    # Composite falls back to title|company when city is missing.
    assert job["dedup_key"] == "platform engineer|solace robotics"


def test_predicted_salary_is_rendered_honestly():
    posting = _postings()[0]  # salary_min/max present, salary_is_predicted == "1"

    job = normalize_adzuna(posting)

    assert job["salary"] is not None
    assert "2200000" in job["salary"]
    assert "3400000" in job["salary"]
    assert "predicted" in job["salary"].lower()


def test_absent_salary_is_null_never_fabricated():
    posting = _postings()[1]  # Site Reliability Engineer — salary_min/max both null

    job = normalize_adzuna(posting)

    assert job["salary"] is None


def test_hybrid_and_onsite_are_text_inferred():
    sre = normalize_adzuna(_postings()[1])  # "In-office role ..."
    platform = normalize_adzuna(_postings()[2])  # "Team is hybrid, two days a week on site."

    assert sre["work_mode"] == "onsite"
    assert platform["work_mode"] == "hybrid"


def test_stable_source_id_used_with_recorded_composite_dedup_key():
    posting = _postings()[0]

    job = normalize_adzuna(posting)

    # Adzuna's own id is reasonably stable per posting → used directly.
    assert job["id"] == "adzuna:4021557831"
    # Recorded separately so a JSearch copy of the same role — which always
    # resolves through the composite — can still be matched as a duplicate.
    assert job["dedup_key"] == "backend engineer, distributed systems|meridian cloud|bangalore"


def test_posting_missing_title_and_company_is_skipped():
    raw = {
        "id": "9999999",
        "title": None,
        "company": {},
        "location": {"area": [], "display_name": ""},
        "description": "Malformed listing missing identity fields.",
        "redirect_url": None,
        "salary_min": None,
        "salary_max": None,
        "salary_is_predicted": "0",
        "contract_time": None,
        "contract_type": None,
        "created": "2026-07-09T06:30:00Z",
    }

    assert normalize_adzuna(raw) is None
