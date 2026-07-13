"""T012 [US1] — unit tests for the idempotency key + within-run dedup
(discovery/dedup.py).

Covers `compute_id`'s two paths — a stable source id (`"<source>:<source_id>"`)
vs. the normalized `title|company|city` composite fallback — and
`dedup_within_run` collapsing duplicate postings in one batch to a single
record, preferring the richer payload deterministically, while dropping
entries with no usable id (FR-011, FR-012, FR-013). Written first
(Constitution VII) — expected to fail until T018 implements `dedup.py`.
"""

from __future__ import annotations

from jobhunter.discovery.dedup import compute_id, dedup_within_run


def test_stable_source_id_is_prefixed_with_source():
    job_id = compute_id(
        source="adzuna",
        source_id="4021557831",
        id_is_stable=True,
        title="Backend Engineer, Distributed Systems",
        company="Meridian Cloud",
        city="Bangalore",
    )

    assert job_id == "adzuna:4021557831"


def test_unstable_source_id_falls_back_to_normalized_composite():
    job_id = compute_id(
        source="jsearch",
        source_id="aggregate-hash-0001",
        id_is_stable=False,
        title="Staff Backend Engineer",
        company="Northwind Systems",
        city="Bangalore",
    )

    assert job_id == "staff backend engineer|northwind systems|bangalore"


def test_composite_normalizes_case_and_whitespace():
    job_id = compute_id(
        source="jsearch",
        source_id="aggregate-hash-0002-dup",
        id_is_stable=False,
        title="  Senior Platform Engineer  ",
        company="riverstone labs",
        city="Bangalore",
    )

    assert job_id == "senior platform engineer|riverstone labs|bangalore"


def test_composite_falls_back_to_title_company_when_city_missing():
    job_id = compute_id(
        source="jsearch",
        source_id="aggregate-hash-0003",
        id_is_stable=False,
        title="Backend Engineer",
        company="Cascade Analytics",
        city="",
    )

    assert job_id == "backend engineer|cascade analytics"


def test_missing_title_and_company_has_no_usable_id():
    job_id = compute_id(
        source="jsearch",
        source_id="aggregate-hash-0004",
        id_is_stable=False,
        title=None,
        company=None,
        city="",
    )

    assert job_id is None


def test_duplicate_postings_in_one_batch_collapse_preferring_richer_payload():
    shared_id = "senior platform engineer|riverstone labs|bangalore"
    sparse = {
        "id": shared_id,
        "source": "jsearch",
        "title": "Senior Platform Engineer",
        "company": "Riverstone Labs",
        "city": "Bangalore",
        "description": None,
        "salary": None,
        "employment_type": None,
        "apply_url": None,
    }
    rich = {
        **sparse,
        "description": "Hybrid role, three days in the Bangalore office.",
        "salary": "2500000-3800000 YEAR",
        "employment_type": "FULLTIME",
        "apply_url": "https://jobs.example.com/apply/0002",
    }

    deduped = dedup_within_run([sparse, rich])

    assert len(deduped) == 1
    assert deduped[0]["description"] == rich["description"]
    assert deduped[0]["salary"] == rich["salary"]
    assert deduped[0]["apply_url"] == rich["apply_url"]


def test_non_duplicate_postings_are_all_preserved():
    a = {"id": "id-a", "description": None}
    b = {"id": "id-b", "description": None}

    deduped = dedup_within_run([a, b])

    assert {job["id"] for job in deduped} == {"id-a", "id-b"}


def test_entries_without_a_usable_id_are_dropped():
    jobs = [
        {"id": None, "description": "no identity"},
        {"id": "keeper", "description": "has identity"},
    ]

    deduped = dedup_within_run(jobs)

    assert [job["id"] for job in deduped] == ["keeper"]
