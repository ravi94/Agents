"""T022 [P] [US3] — integration test proving the "no double alert, ever"
guarantee for US3 ("Alert only on genuinely new, high-scoring jobs").

Runs `scoring.run.run_scoring` twice over the same single above-threshold
fixture job (`scoring:job-pass-all`): the first run scores the job and must
send exactly one notification, stamping `alerted_at`; the second run must
send zero further notifications and must not move `alerted_at` forward, even
though the job's score would still clear the (deliberately zeroed) alerting
threshold. The mechanism this test locks in (per data-model.md's state
transitions and the T027 wiring plan) is two-layered: (1) once a job leaves
`state='new'` for `state='scored'`, a rerun's `state='new'` loop in
`run_scoring` never revisits it, so `alert.run_alerts` never even sees it
again; and (2) independently, `alerted_at` is write-once (data-model.md:
"MUST only ever be written once per job ... a job that already has a
non-null `alerted_at` MUST be skipped by the alert step regardless of its
current score"). This test only needs to observe outcome (1) to pass, but
both layers are part of the guarantee US3 promises.

The alerting threshold is overridden to `0.0` (rather than relying on the
fixture's `scoring_prefs.yaml` value of `0.75`) so this test is decoupled
from the scorer's exact weighted-sum math — any job that reaches
`state=scored` trivially clears a `0.0` bar. This keeps the test about alert
*mechanics* (write-once, no double-send), not scorer calibration.

Written first (Constitution VII): expected to FAIL right now — `obs.notify`
does not exist (T024), `src/jobhunter/scoring/alert.py`'s `run_alerts` does
not exist (T025), `db.mark_alerted` does not exist (T026), and `run.py` does
not call any of this yet (T027), so `ScoreRunSummary.alerted` stays `0` and
`alerted_at` stays unset. The expected failure is on the run-1 assertions
below (`summary.alerted == 1` and/or the notify-call-count/`alerted_at`
assertions that follow it), not an import or fixture-loading error.

Assumptions made writing this test (mirroring test_score_run.py's documented
assumptions for this same orchestrator):
- `run_scoring` resolves the store path itself via the `JOBHUNTER_HOME`-aware
  default, so this test never passes `path=` to `run_scoring` — only to `db`
  calls used for seeding/assertions.
- `run_scoring` calls `db.init_db()` itself, but seeding via `db.upsert_job`
  needs the store to exist first, so this test calls `db.init_db()` up front
  (same as test_score_run.py's `_seed` helper).
- `embeddings.ollama.embed` is patched at its definition site
  (`jobhunter.embeddings.ollama.embed`), matching the module-qualified call
  `scoring.scorer` is expected to make.
- `obs.notify` is patched via `monkeypatch.setattr("jobhunter.obs.notify",
  fake_notify, raising=False)` since it does not exist yet (T024) — the
  `raising=False` is intentional and expected to become unnecessary once
  T024 lands.
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

_JOB_ID = "scoring:job-pass-all"


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
    """Fixture prefs with `alerting.score_threshold` zeroed out.

    Any job that reaches `state=scored` clears a `0.0` bar trivially, so this
    test exercises alert *mechanics* (write-once, no double-send across
    reruns) rather than depending on the scorer's exact weighted-sum output
    clearing the fixture's real `0.75` threshold.
    """
    payload = yaml.safe_load((fixtures_dir / "scoring_prefs.yaml").read_text())
    loaded = Preferences.model_validate(payload)
    return loaded.model_copy(
        update={"alerting": loaded.alerting.model_copy(update={"score_threshold": 0.0})}
    )


@pytest.fixture
def scoring_jobs(fixtures_dir) -> list[dict]:
    all_jobs = json.loads((fixtures_dir / "scoring_jobs.json").read_text())
    return [job for job in all_jobs if job["id"] == _JOB_ID]


def _seed(scoring_jobs: list[dict]) -> None:
    db.init_db()
    for job in scoring_jobs:
        db.upsert_job(job)


def test_rerun_over_same_scored_job_never_double_alerts(profile, prefs, scoring_jobs, monkeypatch):
    assert len(scoring_jobs) == 1, "fixture must contain exactly one seed job"

    notify_calls: list[str] = []

    def _fake_notify(message: str) -> bool:
        notify_calls.append(message)
        return True

    monkeypatch.setattr("jobhunter.obs.notify", _fake_notify, raising=False)

    _seed(scoring_jobs)

    # --- Run 1: job is `state='new'` -> filtered/scored/alerted this run. ---
    summary_1 = run_scoring(profile, prefs)

    assert summary_1.scored == 1
    assert summary_1.alerted == 1

    assert len(notify_calls) == 1

    after_run_1 = db.get_job(_JOB_ID)
    assert after_run_1 is not None
    assert after_run_1["state"] == "scored"
    assert after_run_1["alerted_at"] is not None
    alerted_at_after_run_1 = after_run_1["alerted_at"]

    # --- Run 2: job is now `state='scored'`, so the `state='new'` loop in
    # `run_scoring` never revisits it — nothing to score, nothing to alert. ---
    summary_2 = run_scoring(profile, prefs)

    assert summary_2.scored == 0
    assert summary_2.alerted == 0

    # Still exactly one notification ever sent, across both runs combined.
    assert len(notify_calls) == 1

    after_run_2 = db.get_job(_JOB_ID)
    assert after_run_2 is not None
    assert after_run_2["alerted_at"] == alerted_at_after_run_1
