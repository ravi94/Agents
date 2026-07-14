"""T029 [P] [US4] — unit tests for the bounded re-rank orchestration
(`scoring/rerank.py`).

`run_rerank(jobs, profile, provider, *, path=None, dry_run=False)` is the
opt-in `--rerank` step (spec §US4, tasks.md T034): it slices this run's
scored jobs to the top ~25 by `score`, sends exactly one bounded call to
`LLMProvider.rerank(candidates, profile)`, and writes each returned
`(job_id, reason)` onto that job's row via `store.db` — mirroring
`scoring/alert.py`'s `run_alerts` shape (same file, already implemented; see
`tests/unit/test_alert.py` for the isolated-store/fixture pattern this file
follows).

These tests pin down the orchestration contract, independent of the two
provider-side tasks it depends on:

- T032 (not yet done) will add an abstract `rerank(candidates, profile) ->
  dict[str, str]` method to `LLMProvider` in `src/jobhunter/llm/provider.py`.
- T033 (not yet done) will implement `ClaudeCLIProvider.rerank`.

Because `run_rerank` only calls `provider.rerank(...)` structurally (duck
typing, no `isinstance` check against the ABC), these tests use a small fake
provider defined inline rather than subclassing the real `LLMProvider` — the
ABC can't be instantiated yet anyway since `rerank` isn't an abstract method
on it until T032 lands.

Written first (Constitution VII) — `src/jobhunter/scoring/rerank.py` does not
exist yet, so this file is expected to fail with an import error
(`ModuleNotFoundError`/`ImportError` for `jobhunter.scoring.rerank`) until
T032/T033/T034 land.
"""

from __future__ import annotations

import json

import pytest

from jobhunter.llm.provider import LLMProviderError
from jobhunter.models.profile import Profile
from jobhunter.scoring.rerank import run_rerank
from jobhunter.store import db


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


@pytest.fixture
def profile(fixtures_dir) -> Profile:
    data = json.loads((fixtures_dir / "scoring_profile.json").read_text())
    return Profile.model_validate(data)


class _RecordingProvider:
    """A fake `LLMProvider`: records every `rerank` call it receives.

    Not a subclass of the real `LLMProvider` ABC (see module docstring) —
    `run_rerank` only needs a `.rerank(candidates, profile)` method, so this
    is enough to pin down the orchestration's contract with the provider.
    """

    def __init__(self, result: dict[str, str] | None = None, error: Exception | None = None):
        self.calls: list[dict] = []
        self._result = result if result is not None else {}
        self._error = error

    def rerank(self, candidates: list[dict], profile: Profile) -> dict[str, str]:
        self.calls.append({"candidates": candidates, "profile": profile})
        if self._error is not None:
            raise self._error
        return self._result


def _seed_job(job_id: str, score: float, *, path, **extra) -> dict:
    """Insert a scored job row and return it as `db.get_job` would.

    Mirrors `test_alert.py`'s `_seed_scored_job` helper/pattern: real jobs
    reaching `run_rerank` come from the store (e.g. `list_jobs_by_state`), so
    seeding through `db.upsert_job` + `db.get_job` keeps these tests exercising
    the same shape of dict the real orchestrator will pass in — including
    fields (`salary`, `state`) that must never leak into the provider call.
    """
    payload = {
        "id": job_id,
        "title": extra.pop("title", f"Backend Engineer ({job_id})"),
        "description": extra.pop(
            "description", "Build and own backend services in Python and AWS."
        ),
        "state": extra.pop("state", "scored"),
        "score": score,
        "matched_skills": extra.pop("matched_skills", json.dumps(["Python", "AWS"])),
    }
    payload.update(extra)
    db.upsert_job(payload, path=path)
    return db.get_job(job_id, path=path)


def test_provider_called_exactly_once_with_at_most_25_candidates(profile):
    path = db.init_db()
    # 30 jobs, unique descending scores: job i=0 is the highest score.
    jobs = [
        _seed_job(f"scoring:rerank-{i:02d}", score=100 - i, path=path) for i in range(30)
    ]
    provider = _RecordingProvider(result={})

    # Feed them in a different order than seeded, so the assertion below can
    # only pass if run_rerank sorts by score itself rather than just slicing
    # whatever order `jobs` arrived in.
    run_rerank(list(reversed(jobs)), profile, provider, path=path)

    assert len(provider.calls) == 1
    candidates = provider.calls[0]["candidates"]
    assert len(candidates) == 25

    expected_top_25_ids = {f"scoring:rerank-{i:02d}" for i in range(25)}
    assert {c["id"] for c in candidates} == expected_top_25_ids


def test_candidate_payload_is_redacted_to_title_description_matched_skills(profile):
    path = db.init_db()
    job = _seed_job(
        "scoring:rerank-redact",
        score=88.5,
        path=path,
        salary="45 LPA",
        state="scored",
        title="Staff Backend Engineer",
        description="Own the payments platform end to end.",
        matched_skills=json.dumps(["Python", "Django", "PostgreSQL"]),
    )
    provider = _RecordingProvider(result={})

    run_rerank([job], profile, provider, path=path)

    candidates = provider.calls[0]["candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]

    # Only id/title/description/matched_skills travel to the provider — never
    # the full job row, never tracking state (score/state/alerted_at), never
    # unrelated fields like salary.
    assert set(candidate.keys()) == {"id", "title", "description", "matched_skills"}
    assert candidate["id"] == job["id"]
    assert candidate["title"] == job["title"]
    assert candidate["description"] == job["description"]
    assert candidate["matched_skills"] == job["matched_skills"]
    assert "score" not in candidate
    assert "state" not in candidate
    assert "alerted_at" not in candidate
    assert "salary" not in candidate


def test_provider_receives_profile_skills_and_roles(profile):
    path = db.init_db()
    job = _seed_job("scoring:rerank-profile", score=90, path=path)
    provider = _RecordingProvider(result={})

    run_rerank([job], profile, provider, path=path)

    passed_profile = provider.calls[0]["profile"]
    # The orchestration hands the provider the candidate's profile — the
    # provider (T033) reads `skills`/`roles` off of it; nothing about
    # `prefs.yaml` or store/tracking state is ever in scope here.
    assert passed_profile.skills == profile.skills
    assert passed_profile.roles == profile.roles


def test_success_persists_returned_reasons_and_returns_annotated_count(profile):
    path = db.init_db()
    job_a = _seed_job("scoring:rerank-a", score=95, path=path)
    job_b = _seed_job("scoring:rerank-b", score=90, path=path)
    job_c = _seed_job("scoring:rerank-c", score=85, path=path)
    provider = _RecordingProvider(
        result={
            job_a["id"]: "Strong scope match: owns payments infra end to end.",
            job_b["id"]: "Comp and location both clear the bar comfortably.",
        }
    )

    annotated = run_rerank([job_a, job_b, job_c], profile, provider, path=path)

    assert annotated == 2
    assert (
        db.get_job(job_a["id"], path=path)["reason"]
        == "Strong scope match: owns payments infra end to end."
    )
    assert (
        db.get_job(job_b["id"], path=path)["reason"]
        == "Comp and location both clear the bar comfortably."
    )
    assert db.get_job(job_c["id"], path=path)["reason"] is None


def test_dry_run_calls_provider_but_writes_nothing(profile):
    path = db.init_db()
    job = _seed_job("scoring:rerank-dry", score=99, path=path)
    provider = _RecordingProvider(result={job["id"]: "Would be a great fit."})

    annotated = run_rerank([job], profile, provider, path=path, dry_run=True)

    assert len(provider.calls) == 1
    assert annotated == 1
    assert db.get_job(job["id"], path=path)["reason"] is None


def test_provider_error_is_caught_leaves_reasons_empty_and_returns_zero(profile):
    path = db.init_db()
    job_a = _seed_job("scoring:rerank-err-a", score=95, path=path)
    job_b = _seed_job("scoring:rerank-err-b", score=90, path=path)
    provider = _RecordingProvider(error=LLMProviderError("provider call failed"))

    annotated = run_rerank([job_a, job_b], profile, provider, path=path)  # must not raise

    assert annotated == 0
    assert db.get_job(job_a["id"], path=path)["reason"] is None
    assert db.get_job(job_b["id"], path=path)["reason"] is None


def test_provider_timeout_is_caught_without_raising(profile):
    path = db.init_db()
    job = _seed_job("scoring:rerank-timeout", score=95, path=path)
    provider = _RecordingProvider(error=TimeoutError("provider timed out"))

    annotated = run_rerank([job], profile, provider, path=path)  # must not raise

    assert annotated == 0
    assert db.get_job(job["id"], path=path)["reason"] is None
