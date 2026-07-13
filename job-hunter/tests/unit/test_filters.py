"""T008 [P] [US1] — unit tests for the hard-filter gate (`scoring/filters.py`).

`apply_filters(job, prefs)` is the black-box gate every discovered job passes
through before scoring (contracts/scoring_algorithm.md "Hard filters"): a job
failing any of `locations`, `work_modes`, `company_types`, `comp_floor_lpa`,
or `seniority_floor` is filtered out, but `failed_filters` must collect
*every* violated dimension (not just the first) so the eventual
`reason="failed: <comma-joined dimensions>"` is complete. These tests assert
only the resulting `FilterResult` (passed / failed_filters) — never how
`filters.py` infers company type or seniority from free text internally,
since that inference is an implementation detail left to T012.

Written first (Constitution VII) — expected to fail right now with an
import error until T012 implements `jobhunter.scoring.filters`.

Assumptions made while writing this test (T012's implementer should satisfy
these, per the contract + fixture authoring intent):
- Salary strings like "45 LPA" / "12 LPA" parse to LPA floats (45.0 / 12.0)
  for the `comp_floor_lpa` comparison; `salary: null` is missing-data
  pass-through.
- Company type is inferred from free text in `company` and/or `description`
  (e.g. "IT staffing and recruitment agency" -> "staffing_agency"; "Series A
  startup" -> "startup"; "Fortune 500 multinational enterprise conglomerate"
  -> something outside {startup, midsize}, e.g. "enterprise"). A job with no
  such signal text (e.g. plain "Build and maintain internal services") has an
  undeterminable company type and passes both allow/deny checks.
- Seniority is inferred from `title` (e.g. "Senior Backend Engineer" ->
  "senior", "Junior Backend Engineer" -> "junior"); a title with no seniority
  word (e.g. "Backend Engineer") has undeterminable seniority and passes
  through the seniority_floor check.
- `locations` matches against either `city` or `location` case-insensitively
  against `hard_filters.locations`; `work_mode == "remote"` always passes
  `locations` regardless of city (per contract table), which the
  `scoring:job-pass-all`-style fixtures rely on implicitly (all fixture jobs
  happen to have Bangalore *and* remote/hybrid, so this test suite does not
  by itself distinguish "remote job in a disallowed city passes locations"
  from "Bangalore job passes locations" — that nuance is covered by the
  contract, not re-derived here from the shared fixtures).
"""

from __future__ import annotations

import json

import pytest
import yaml

from jobhunter.models.preferences import Preferences
from jobhunter.scoring.filters import apply_filters


@pytest.fixture
def prefs(fixtures_dir) -> Preferences:
    data = yaml.safe_load((fixtures_dir / "scoring_prefs.yaml").read_text())
    return Preferences.model_validate(data)


@pytest.fixture
def jobs(fixtures_dir) -> dict[str, dict]:
    raw = json.loads((fixtures_dir / "scoring_jobs.json").read_text())
    return {job["id"]: job for job in raw}


def test_job_passing_every_filter_is_not_filtered(jobs, prefs):
    result = apply_filters(jobs["scoring:job-pass-all"], prefs)

    assert result.passed is True
    assert result.failed_filters == []


def test_wrong_location_fails_locations_only(jobs, prefs):
    result = apply_filters(jobs["scoring:job-fail-location"], prefs)

    assert result.passed is False
    assert result.failed_filters == ["locations"]


def test_disallowed_work_mode_fails_work_modes_only(jobs, prefs):
    result = apply_filters(jobs["scoring:job-fail-work-mode"], prefs)

    assert result.passed is False
    assert result.failed_filters == ["work_modes"]


def test_denied_company_type_fails_company_types_only(jobs, prefs):
    result = apply_filters(jobs["scoring:job-fail-company-type-deny"], prefs)

    assert result.passed is False
    assert result.failed_filters == ["company_types"]


def test_company_type_outside_allow_list_fails_company_types_only(jobs, prefs):
    result = apply_filters(jobs["scoring:job-fail-company-type-allow"], prefs)

    assert result.passed is False
    assert result.failed_filters == ["company_types"]


def test_salary_below_comp_floor_fails_comp_floor_only(jobs, prefs):
    result = apply_filters(jobs["scoring:job-fail-comp"], prefs)

    assert result.passed is False
    assert result.failed_filters == ["comp_floor_lpa"]


def test_seniority_below_floor_fails_seniority_floor_only(jobs, prefs):
    result = apply_filters(jobs["scoring:job-fail-seniority"], prefs)

    assert result.passed is False
    assert result.failed_filters == ["seniority_floor"]


def test_missing_company_type_salary_and_seniority_all_pass_through(jobs, prefs):
    result = apply_filters(jobs["scoring:job-pass-missing-data"], prefs)

    assert result.passed is True
    assert result.failed_filters == []


def test_unknown_work_mode_passes_through(jobs, prefs):
    result = apply_filters(jobs["scoring:job-pass-unknown-work-mode"], prefs)

    assert result.passed is True
    assert result.failed_filters == []


def test_multiple_violated_dimensions_are_all_collected_not_just_first(jobs, prefs):
    # Wrong location (Mumbai, onsite -> also fails work_modes) AND below the
    # comp floor. Built from the "pass-all" shape so every other dimension
    # (company type, seniority) still passes, isolating locations +
    # work_modes + comp_floor_lpa as the only failures.
    job = dict(jobs["scoring:job-pass-all"])
    job.update(
        id="scoring:job-fail-location-and-comp",
        location="Mumbai, India",
        city="Mumbai",
        work_mode="onsite",
        salary="12 LPA",
    )

    result = apply_filters(job, prefs)

    assert result.passed is False
    assert set(result.failed_filters) == {"locations", "work_modes", "comp_floor_lpa"}


def test_wrong_location_and_below_seniority_floor_both_collected(jobs, prefs):
    # Wrong location (and not remote, so locations fails) plus a junior title
    # (seniority fails), everything else kept identical to the passing job.
    job = dict(jobs["scoring:job-pass-all"])
    job.update(
        id="scoring:job-fail-location-and-seniority",
        title="Junior Backend Engineer",
        location="Mumbai, India",
        city="Mumbai",
        work_mode="hybrid",
    )

    result = apply_filters(job, prefs)

    assert result.passed is False
    assert set(result.failed_filters) == {"locations", "seniority_floor"}
