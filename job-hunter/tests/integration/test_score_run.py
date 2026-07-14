"""T011 [P] [US1] — integration test for the scoring run (scoring/run.py).

End-to-end filter → score → persist against 9 fixture jobs (all `state=new`),
a fixture profile/prefs pair, and a temp `JOBHUNTER_HOME`: jobs failing a hard
filter land as `state=filtered_out` with a `reason` and no score/breakdown/
matched_skills; jobs passing every filter land as `state=scored` with a
persisted `score`, JSON `breakdown`, and JSON `matched_skills`; the run
reports `filtered_out`/`scored` counts on its `ScoreRunSummary`. `dry_run`
mirrors M2's `run_discovery` `dry_run` behavior — same counts reported, but
nothing is written to the store. Written first (Constitution VII) — expected
to fail until T014 implements `scoring.run.run_scoring` (and T012/T013
implement `scoring.filters`/`scoring.scorer`, which it depends on).

Assumptions made writing this test (for T012/T013/T014's implementer):
- `run_scoring` resolves the store path itself via the `JOBHUNTER_HOME`-aware
  default (same convention as `run_discovery`), so this test never passes a
  `path=` kwarg to `run_scoring` — only to `db` calls used for seeding/
  assertions, matching `test_discover_run.py`.
- `run_scoring` calls `db.init_db()` itself (mirrors `run_discovery`), so this
  test does not call it before seeding — seeding via `db.upsert_job` still
  requires the store to exist, so an explicit `db.init_db()` precedes seeding
  here, exactly as `test_discover_run.py` does not need it (its store is
  created by `run_discovery` before any read) but ours needs rows present
  *before* the run, so we call `init_db()` up front.
- `embeddings.ollama.embed` is patched at its definition site
  (`jobhunter.embeddings.ollama.embed`) since `scoring.scorer` is expected to
  call it via `from jobhunter.embeddings import ollama; ollama.embed(...)`
  (module-qualified), not a rebound top-level import — this matches the task
  brief's exact monkeypatch target.
- The fixture jobs' `salary` strings (e.g. "45 LPA") are parsed internally by
  `scoring.filters`/`scoring.scorer`; this test does not assert on the parsed
  numeric value, only on pass/fail outcomes and the persisted shapes.
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


def test_scoring_run_filters_and_scores_fixture_jobs(profile, prefs, scoring_jobs):
    _seed(scoring_jobs)

    summary = run_scoring(profile, prefs)

    # 6 of the 9 fixture jobs each fail exactly one hard-filter dimension;
    # the remaining 3 pass every filter (see fixture-authoring intent noted
    # in the task brief).
    assert summary.filtered_out == 6
    assert summary.scored == 3
    # 2 of the 3 scored fixture jobs clear the fixture prefs' 0.75 alert
    # threshold (US3); alerted_at is stamped even with no ntfy topic set in
    # the test env (FR-010 — only the push itself is skipped, not the count).
    assert summary.alerted == 2
    assert summary.reranked == 0

    filtered = db.get_job("scoring:job-fail-comp")
    assert filtered is not None
    assert filtered["state"] == "filtered_out"
    assert isinstance(filtered["reason"], str) and filtered["reason"]
    assert "comp_floor_lpa" in filtered["reason"]
    assert filtered["score"] is None
    assert filtered["breakdown"] is None
    assert filtered["matched_skills"] is None

    scored = db.get_job("scoring:job-pass-all")
    assert scored is not None
    assert scored["state"] == "scored"
    assert isinstance(scored["score"], float)
    assert 0.0 <= scored["score"] <= 1.0

    breakdown = json.loads(scored["breakdown"])
    assert breakdown["overall"] == pytest.approx(scored["score"])
    assert set(breakdown["components"]) == {
        "work_life_balance",
        "stability",
        "scope",
        "comp",
    }

    matched_skills = json.loads(scored["matched_skills"])
    assert isinstance(matched_skills, list)


def test_summary_names_the_top_scored_job_and_its_breakdown(profile, prefs, scoring_jobs):
    """T020 — SC-004: the top contributing factor is legible without a
    separate query, so the summary itself must carry the highest-ranked
    job's title and breakdown, not just aggregate counts."""
    _seed(scoring_jobs)

    summary = run_scoring(profile, prefs)

    assert summary.top_job_title is not None
    assert summary.top_breakdown is not None

    all_scored_titles = {
        job["title"]
        for job in scoring_jobs
        if db.get_job(job["id"])["state"] == "scored"
    }
    assert summary.top_job_title in all_scored_titles

    best_score = max(
        db.get_job(job["id"])["score"]
        for job in scoring_jobs
        if db.get_job(job["id"])["state"] == "scored"
    )
    assert summary.top_breakdown.overall == pytest.approx(best_score)


def test_no_scored_jobs_leaves_top_fields_unset(profile, prefs):
    db.init_db()  # no `state='new'` jobs seeded — nothing to filter or score

    summary = run_scoring(profile, prefs)

    assert summary.scored == 0
    assert summary.top_job_title is None
    assert summary.top_breakdown is None


def test_dry_run_reports_summary_but_writes_nothing(profile, prefs, scoring_jobs):
    _seed(scoring_jobs)

    summary = run_scoring(profile, prefs, dry_run=True)

    assert summary.filtered_out == 6
    assert summary.scored == 3

    for job in scoring_jobs:
        stored = db.get_job(job["id"])
        assert stored is not None
        assert stored["state"] == "new"
        assert stored["score"] is None
        assert stored["breakdown"] is None
        assert stored["matched_skills"] is None
        assert stored["reason"] is None
