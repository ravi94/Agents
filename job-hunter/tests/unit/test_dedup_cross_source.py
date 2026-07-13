"""T029 [P] [US3] — unit tests for cross-source dedup (discovery/dedup.py).

The same role posted on both JSearch and Adzuna has no shared source id:
JSearch always resolves through the normalized composite
(contracts/source_mapping.md "Cross-source dedup"), while Adzuna prefers its
stable source id but additionally records that same composite as
`dedup_key`. `dedup_within_run` MUST collapse postings that share a resolved
key (`dedup_key`, falling back to `id`) into one record, preferring the
richer payload deterministically — even though the two source ids differ.
Written first (Constitution VII) — expected to fail until T031/T032 (Adzuna
adapter + normalization) and T033 (cross-source collapse in `dedup.py`) land.
"""

from __future__ import annotations

import json
from pathlib import Path

from jobhunter.discovery.dedup import dedup_within_run
from jobhunter.discovery.normalize import normalize_adzuna, normalize_jsearch

FIXTURE = Path(__file__).parent.parent / "fixtures" / "source_dupe_pair.json"


def _pair() -> tuple[dict, dict]:
    payload = json.loads(FIXTURE.read_text())
    jsearch_job = normalize_jsearch(payload["jsearch"]["data"]["jobs"][0])
    adzuna_job = normalize_adzuna(payload["adzuna"]["results"][0])
    return jsearch_job, adzuna_job


def test_same_role_from_both_sources_resolves_to_the_same_key():
    jsearch_job, adzuna_job = _pair()

    # JSearch always resolves through the composite; Adzuna's own id differs,
    # but its recorded dedup_key matches JSearch's composite id exactly.
    assert jsearch_job["id"] == "senior data engineer|vertex analytics|bangalore"
    assert adzuna_job["id"] == "adzuna:4021559120"
    assert adzuna_job["dedup_key"] == jsearch_job["id"]


def test_cross_source_duplicate_collapses_to_one_record_preferring_richer_payload():
    jsearch_job, adzuna_job = _pair()

    deduped = dedup_within_run([jsearch_job, adzuna_job])

    assert len(deduped) == 1
    # Adzuna's copy carries salary, a fuller description, and contract
    # details that JSearch's copy lacks — it is the richer record and wins.
    assert deduped[0]["source"] == "adzuna"
    assert deduped[0]["id"] == "adzuna:4021559120"
    assert deduped[0]["salary"] is not None
    assert deduped[0]["description"] is not None


def test_winner_is_deterministic_regardless_of_input_order():
    jsearch_job, adzuna_job = _pair()

    deduped = dedup_within_run([adzuna_job, jsearch_job])

    assert len(deduped) == 1
    assert deduped[0]["source"] == "adzuna"


def test_non_duplicate_cross_source_postings_are_both_preserved():
    jsearch_job, _ = _pair()
    other = normalize_adzuna(
        {
            "id": "4021560000",
            "title": "Staff Site Reliability Engineer",
            "company": {"display_name": "Distinct Company"},
            "location": {"area": ["India", "Karnataka", "Bangalore"], "display_name": "Bangalore"},
            "description": "Unrelated role, different employer.",
            "redirect_url": "https://www.adzuna.in/land/ad/4021560000",
            "salary_min": None,
            "salary_max": None,
            "salary_is_predicted": "0",
            "contract_time": "full_time",
            "contract_type": None,
            "created": "2026-07-09T08:00:00Z",
        }
    )

    deduped = dedup_within_run([jsearch_job, other])

    assert {job["id"] for job in deduped} == {jsearch_job["id"], other["id"]}
