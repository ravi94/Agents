"""T031 [P] [US4] — integration test pinning down the optional re-rank pass
("Prioritize the shortlist further with an LLM" — US4) as a strict opt-in
addition on top of `scoring.run.run_scoring`.

Seeds 30 `state='new'` jobs — variants of the fixture's `scoring:job-pass-all`
job (same location/work_mode/company/employment_type/title, so every variant
clears the exact same hard filters that job already clears) — and exercises
two scenarios:

1. **`rerank=True`, with a fake provider injected via `provider=`**: after
   filter -> score, the run must call `provider.rerank(candidates, profile)`
   exactly once with at most 25 candidates (this run's scored survivors,
   capped to the top ~25 by `score`), and only those top-25 jobs' `reason`
   column gets the returned per-job reason written — every other scored
   survivor's `reason` stays `NULL`. `summary.reranked` reports the capped
   count (25), not the full `scored` count (30).
2. **`rerank=False` (the default, and also the "not passed at all" case)**:
   `summary.reranked` stays `0`, no job's `reason` is touched by a rerank
   pass, and the filter/score/alert counts are byte-for-byte identical to
   plain `run_scoring(profile, prefs)` with no rerank-related arguments at
   all — i.e. `--rerank` is a non-event for the US1-US3 pipeline when absent.

Written first (Constitution VII): expected to FAIL right now with
`TypeError: run_scoring() got an unexpected keyword argument 'rerank'` (or
`'provider'`) — `run_scoring` (src/jobhunter/scoring/run.py) does not yet
accept either keyword (T035), `scoring/rerank.py`'s `run_rerank` does not yet
exist (T034), and `LLMProvider.rerank` is not yet declared (T032/T033). This
test intentionally exercises `rerank=True` in its very first `run_scoring`
call so the TypeError surfaces immediately, before any filter/score/alert
logic runs; the second test's first `run_scoring(profile, prefs)` call (no
rerank kwargs) is expected to succeed exactly as `test_score_run.py` already
proves, with the TypeError instead surfacing on its second call
(`rerank=False`), which is likewise the point at which this test currently
fails.

Assumptions made writing this test (for T032-T035's implementer):
- `run_scoring` resolves the store path itself via the `JOBHUNTER_HOME`-aware
  default (same convention as every sibling integration test here), so no
  `path=` kwarg is ever passed to `run_scoring` — only to `db` calls used for
  seeding/assertions.
- `run_scoring` never constructs a real `ClaudeCLIProvider` itself; the fake
  provider below is injected directly via `provider=`, matching the task
  brief's statement that provider construction is the CLI's job (T035's other
  half), not `run_scoring`'s.
- The fake provider is a plain duck-typed object (not a subclass of
  `jobhunter.llm.provider.LLMProvider`) since that ABC does not yet declare
  the abstract `rerank` method (T032) — subclassing it here would couple this
  test's timing to T032 landing first, which the task ordering does not
  guarantee.
- `embeddings.ollama.embed` is patched at its definition site
  (`jobhunter.embeddings.ollama.embed`), matching every sibling test's target.
  Unlike the fixed single-vector fake used by `test_score_run.py` and
  `test_score_rerun_no_realert.py`, this test's fake embed is *text-dependent*
  (a small deterministic hash of the input string): with a fixed embedding,
  every synthesized job would land on the exact same `scope` component (and
  therefore the same `overall` score, since `comp` also saturates at `1.0`
  for every job here — see below), making "top-25-by-score" ambiguous. A
  text-dependent fake keeps the test deterministic and Ollama-free while
  still giving each of the 30 synthesized jobs a distinguishable score.
- Salary is varied slightly per synthesized job (`"45 LPA"` .. `"74 LPA"`) per
  the task brief's suggested fixture-construction approach, but this
  intentionally does *not* drive the score differentiation: `comp`'s formula
  is `min(salary_lpa / comp_floor_lpa, 1.0)`, and the fixture's
  `comp_floor_lpa` is `25`, so every salary in this fixture's range saturates
  `comp` at `1.0` regardless — the same is structurally true for *any* salary
  that also has to clear the hard `comp_floor_lpa` filter to reach
  `state=scored` in the first place. The actual score differentiation this
  test relies on comes from the text-dependent fake embed's effect on the
  `scope` component instead.
"""

from __future__ import annotations

import hashlib
import json

import pytest
import yaml

from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.scoring.run import run_scoring
from jobhunter.store import db

_NUM_JOBS = 30
_RERANK_CAP = 25


def _fake_embed(text: str, **kwargs) -> list[float]:
    """Deterministic, text-dependent stand-in for a live Ollama embedding.

    Ollama-free and reproducible, but (unlike the fixed single-vector fakes
    used elsewhere) varies with the input text so each synthesized job below
    gets a distinguishable `scope` component and therefore a distinguishable
    `overall` score — required for this test's "top-25-by-score" assertions
    to be well-defined.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in digest[:8]]


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


def _make_rerank_jobs(n: int = _NUM_JOBS) -> list[dict]:
    """`n` variants of the fixture's `scoring:job-pass-all` job.

    Every variant shares that job's exact location/work_mode/company/
    employment_type/title, so every variant clears the same hard filters it
    already clears (per `tests/fixtures/scoring_jobs.json` +
    `tests/fixtures/scoring_prefs.yaml`) and reaches `state=scored`. Only
    `id`, `description` (drives the text-dependent fake embed, and therefore
    `score`), `salary`, and `apply_url` vary per job.
    """
    jobs = []
    for i in range(n):
        jobs.append(
            {
                "id": f"scoring:rerank-{i:02d}",
                "source": "jsearch",
                "title": "Senior Backend Engineer",
                "company": "BuildStack Technologies",
                "location": "Bangalore, India",
                "city": "Bangalore",
                "country": "India",
                "work_mode": "remote",
                "description": (
                    "Series A startup building a payments platform. Small "
                    "team, high ownership, fast-paced. Python, Django, "
                    f"PostgreSQL, AWS, Kubernetes. Track record variant {i}."
                ),
                "employment_type": "full_time",
                "salary": f"{45 + i} LPA",
                "apply_url": f"https://example.com/jobs/rerank-{i}",
                "state": "new",
            }
        )
    return jobs


def _seed(jobs: list[dict]) -> None:
    db.init_db()
    for job in jobs:
        db.upsert_job(job)


class _FakeRerankProvider:
    """Duck-typed stand-in for `LLMProvider.rerank` — no live `claude` call.

    Records every call it receives (for the "exactly once, bounded" assertion)
    and returns a synthetic, deterministic reason for every candidate it was
    given, so the caller (`run_rerank`, T034) has something real to write into
    each job's `reason` column.
    """

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def rerank(self, candidates: list[dict], profile: Profile) -> dict[str, str]:
        self.calls.append(candidates)
        return {c["id"]: f"reason for {c['id']}" for c in candidates}


def test_rerank_enabled_calls_provider_once_and_sets_reason_on_top_25(profile, prefs):
    jobs = _make_rerank_jobs()
    _seed(jobs)

    fake_provider = _FakeRerankProvider()

    summary = run_scoring(profile, prefs, rerank=True, provider=fake_provider)

    assert summary.scored >= 25
    # Capped to the top ~25, not the full `scored` count (30).
    assert summary.reranked == _RERANK_CAP

    assert len(fake_provider.calls) == 1
    assert len(fake_provider.calls[0]) <= _RERANK_CAP

    scored_rows = [db.get_job(job["id"]) for job in jobs]
    scored_rows = [row for row in scored_rows if row is not None and row["state"] == "scored"]
    ranked = sorted(scored_rows, key=lambda row: row["score"], reverse=True)

    top_25_ids = {row["id"] for row in ranked[:_RERANK_CAP]}
    rest_ids = {row["id"] for row in ranked[_RERANK_CAP:]}

    for job_id in top_25_ids:
        stored = db.get_job(job_id)
        assert stored["reason"] == f"reason for {job_id}"

    for job_id in rest_ids:
        stored = db.get_job(job_id)
        assert stored["reason"] is None


def test_rerank_disabled_behaves_identically_to_baseline_pipeline(
    profile, prefs, monkeypatch, tmp_path
):
    jobs = _make_rerank_jobs()

    # --- Store 1: plain run_scoring(profile, prefs) -- no rerank kwargs at
    # all, exactly what test_score_run.py already exercises and asserts on.
    baseline_home = tmp_path / "baseline"
    monkeypatch.setenv("JOBHUNTER_HOME", str(baseline_home))
    _seed(jobs)
    baseline_summary = run_scoring(profile, prefs)

    # --- Store 2: fresh isolated store, same fixture jobs, but explicitly
    # rerank=False -- must be indistinguishable from the baseline above.
    explicit_home = tmp_path / "explicit-rerank-false"
    monkeypatch.setenv("JOBHUNTER_HOME", str(explicit_home))
    _seed(jobs)
    explicit_summary = run_scoring(profile, prefs, rerank=False)

    assert explicit_summary.reranked == 0
    assert explicit_summary.scored == baseline_summary.scored
    assert explicit_summary.filtered_out == baseline_summary.filtered_out
    assert explicit_summary.alerted == baseline_summary.alerted

    for job in jobs:
        stored = db.get_job(job["id"])
        assert stored is not None
        if stored["state"] == "scored":
            # No rerank pass ran, so nothing wrote a reason onto a scored job
            # (the `reason` column is otherwise only ever set by the filter
            # step, and this job passed every filter).
            assert stored["reason"] is None
