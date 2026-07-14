"""T018 [P] [US2] — breakdown round-trips and the atomicity rule, store-wide.

`test_score_run.py` (T011) already checks the persisted shape on one scored
job. This test runs the full fixture set through `run_scoring` and asserts
the explainability guarantee holds across *every* row the run touches:

- every `state=scored` row's `breakdown` column is valid JSON that round-trips
  to the same shape `scorer.py` produces, queryable directly via `db.get_job`
  with no recomputation;
- no row ever carries a non-null `score` alongside a null `breakdown`, and no
  `filtered_out` row carries a `score`/`breakdown` at all (data-model.md's
  atomicity rule).

Written first per Constitution VII — expected to pass already given T013/T014
(this locks the guarantee in place before T019 hardens it further).
"""

from __future__ import annotations

import json

import pytest
import yaml

from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.scoring.run import run_scoring
from jobhunter.store import db

_FAKE_EMBEDDING = [0.1, 0.2, 0.3]


def _fake_embed(text: str, **kwargs) -> list[float]:
    return list(_FAKE_EMBEDDING)


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


@pytest.fixture(autouse=True)
def _mock_embed(monkeypatch):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _fake_embed)


@pytest.fixture
def profile(fixtures_dir) -> Profile:
    payload = json.loads((fixtures_dir / "scoring_profile.json").read_text())
    return Profile.model_validate(payload)


@pytest.fixture
def prefs(fixtures_dir) -> Preferences:
    payload = yaml.safe_load((fixtures_dir / "scoring_prefs.yaml").read_text())
    return Preferences.model_validate(payload)


@pytest.fixture
def scoring_jobs(fixtures_dir) -> list[dict]:
    return json.loads((fixtures_dir / "scoring_jobs.json").read_text())


def _seed(scoring_jobs: list[dict]) -> None:
    db.init_db()
    for job in scoring_jobs:
        db.upsert_job(job)


def test_every_scored_row_breakdown_round_trips_without_recomputation(
    profile, prefs, scoring_jobs
):
    _seed(scoring_jobs)

    summary = run_scoring(profile, prefs)
    assert summary.scored > 0  # sanity: the fixture set has survivors

    scored_rows = [
        db.get_job(job["id"])
        for job in scoring_jobs
        if db.get_job(job["id"])["state"] == "scored"
    ]
    assert len(scored_rows) == summary.scored

    for row in scored_rows:
        breakdown = json.loads(row["breakdown"])  # must be valid JSON, no recomputation
        assert breakdown["overall"] == pytest.approx(row["score"])
        assert set(breakdown["components"]) == {
            "work_life_balance",
            "stability",
            "scope",
            "comp",
        }
        for component in breakdown["components"].values():
            assert 0.0 <= component["value"] <= 1.0
            assert isinstance(component["weight"], float)
            assert isinstance(component["inferred"], bool)
        assert isinstance(breakdown["computed_at"], str) and breakdown["computed_at"]

        matched_skills = json.loads(row["matched_skills"])
        assert isinstance(matched_skills, list)


def test_no_row_has_score_without_breakdown_or_breakdown_without_score(
    profile, prefs, scoring_jobs
):
    _seed(scoring_jobs)

    run_scoring(profile, prefs)

    for job in scoring_jobs:
        row = db.get_job(job["id"])
        has_score = row["score"] is not None
        has_breakdown = row["breakdown"] is not None
        assert has_score == has_breakdown, (
            f"job {row['id']!r} has score={row['score']!r} "
            f"breakdown={row['breakdown']!r} — atomicity violated"
        )
        if row["state"] == "filtered_out":
            assert not has_score
            assert not has_breakdown
            assert row["matched_skills"] is None
