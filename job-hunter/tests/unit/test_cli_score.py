"""T015/T016 — CLI wiring and observability for `jobhunter score`.

Mirrors `test_cli_discover.py`'s pattern for the M2 command: missing
`profile.json`/`prefs.yaml` are actionable stderr errors with a non-zero exit
(fail before the store is touched); a zero-`state=new` store is a clean,
zero-summary no-op at exit `0`; a real run over fixture jobs prints the
`filtered_out`/`scored`/`alerted`/`reranked` summary shape from
contracts/cli.md; `--dry-run` writes nothing; and only an unexpected error
that prevents the run from completing exits non-zero and fires the ntfy
error signal via `obs.notify_error` (T016), per the existing M1/M2 pattern.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from jobhunter import config
from jobhunter.cli import main

FIXTURES = "tests/fixtures"


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _mock_embed(monkeypatch):
    monkeypatch.setattr(
        "jobhunter.embeddings.ollama.embed", lambda text, **kwargs: [0.1, 0.2, 0.3]
    )


def _write_profile_and_prefs(home):
    shutil.copy(f"{FIXTURES}/scoring_profile.json", home / "profile.json")
    shutil.copy(f"{FIXTURES}/scoring_prefs.yaml", home / "prefs.yaml")


def test_missing_profile_errors_before_touching_store(capsys, _isolated_home):
    shutil.copy(f"{FIXTURES}/scoring_prefs.yaml", _isolated_home / "prefs.yaml")

    rc = main(["score"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert "profile" in err


def test_missing_prefs_errors(capsys, _isolated_home):
    shutil.copy(f"{FIXTURES}/scoring_profile.json", _isolated_home / "profile.json")

    rc = main(["score"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert "prefs init" in err


def test_no_new_jobs_is_a_clean_noop(capsys, _isolated_home):
    _write_profile_and_prefs(_isolated_home)

    rc = main(["score"])

    assert rc == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert "filtered_out: 0   scored: 0   alerted: 0   reranked: 0" in out


def test_score_run_filters_and_scores_fixture_jobs(capsys, _isolated_home):
    from jobhunter.store import db

    _write_profile_and_prefs(_isolated_home)
    db.init_db()
    jobs = json.loads((Path(FIXTURES) / "scoring_jobs.json").read_text())
    for job in jobs:
        db.upsert_job(job)

    rc = main(["score"])

    assert rc == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out.startswith("Scoring run ")
    assert "complete." in out
    # 2 of the 3 scored fixture jobs clear the fixture prefs' 0.75 alert
    # threshold; `alerted_at` is still stamped even with no ntfy topic
    # configured in the test env (FR-010 — only the actual push is skipped).
    assert "filtered_out: 6   scored: 3   alerted: 2   reranked: 0" in out


def test_summary_surfaces_top_job_and_its_top_contributing_factor(capsys, _isolated_home):
    """T020 — SC-004: a seeker can identify the top contributing factor
    behind the highest-ranked job's score straight from the run summary."""
    from jobhunter.store import db

    _write_profile_and_prefs(_isolated_home)
    db.init_db()
    jobs = json.loads((Path(FIXTURES) / "scoring_jobs.json").read_text())
    for job in jobs:
        db.upsert_job(job)

    rc = main(["score"])

    assert rc == 0
    out, _err = capsys.readouterr()
    # `_mock_embed` returns the same vector for every text, so `scope`
    # (cosine similarity of identical vectors, rescaled to 1.0) is the
    # deterministic top-weighted factor across every scored fixture job.
    assert "top:" in out.lower()
    assert "scope" in out


def test_dry_run_writes_nothing_and_exits_zero(capsys, _isolated_home):
    from jobhunter.store import db

    _write_profile_and_prefs(_isolated_home)
    db.init_db()
    jobs = json.loads((Path(FIXTURES) / "scoring_jobs.json").read_text())
    for job in jobs:
        db.upsert_job(job)

    rc = main(["score", "--dry-run"])

    assert rc == 0
    out, _err = capsys.readouterr()
    # dry-run still reports the count that *would* be alerted, but writes
    # nothing — checked below via alerted_at staying null on every row.
    assert "filtered_out: 6   scored: 3   alerted: 2   reranked: 0" in out
    for job in jobs:
        stored = db.get_job(job["id"])
        assert stored["state"] == "new"
        assert stored["alerted_at"] is None


def test_summary_run_id_matches_log_correlation_id(capsys, _isolated_home):
    _write_profile_and_prefs(_isolated_home)

    rc = main(["score"])

    assert rc == 0
    out, _err = capsys.readouterr()
    prefix, _, _rest = out.partition(" complete.")
    run_id = prefix.removeprefix("Scoring run ")

    log_text = config.log_path().read_text()
    assert f"[run={run_id}]" in log_text
    assert "[run=-]" not in log_text


def test_whole_run_failure_exits_nonzero_and_notifies(capsys, monkeypatch, _isolated_home):
    """An unexpected error fails the whole run and fires the ntfy error signal."""
    _write_profile_and_prefs(_isolated_home)
    monkeypatch.setenv("JOBHUNTER_NTFY_TOPIC", "test-topic")

    notified = []
    monkeypatch.setattr(
        "jobhunter.obs.notify_error", lambda message, **kwargs: notified.append(message) or True
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("store unwritable")

    monkeypatch.setattr("jobhunter.scoring.run.run_scoring", _boom)

    rc = main(["score"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert len(notified) == 1
    assert "score" in notified[0]
