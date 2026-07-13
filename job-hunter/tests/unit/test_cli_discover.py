"""T036 — CLI error/exit-code behavior for `jobhunter discover` (contracts/cli.md).

Mirrors `test_cli_errors.py`'s pattern for the M2 command: missing
`profile.json`/`prefs.yaml` are actionable stderr errors with a non-zero exit
(fail before any source is touched); a profile/prefs pair yielding no usable
query is a clean, zero-summary no-op at exit `0` (edge case, FR-003); and only
an unexpected error that prevents the run from completing — never a per-source
failure — exits non-zero (FR-017/018 vs FR-024).
"""

from __future__ import annotations

import json

import pytest
import yaml

from jobhunter import config
from jobhunter.cli import main


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))
    return tmp_path


def _write_profile(home, *, roles):
    (home / "profile.json").write_text(
        json.dumps(
            {
                "skills": ["Python"],
                "roles": roles,
                "seniority": "senior",
                "source_resume_filename": "resume.pdf",
                "parsed_at": "2026-07-01T00:00:00+00:00",
            }
        )
    )


def _write_prefs(home):
    (home / "prefs.yaml").write_text(
        yaml.safe_dump(
            {
                "hard_filters": {
                    "locations": ["Bangalore"],
                    "work_modes": ["remote", "hybrid", "onsite"],
                    "comp_floor_lpa": 40,
                    "seniority_floor": "senior",
                },
                "soft_weights": {
                    "work_life_balance": 0.25,
                    "stability": 0.25,
                    "scope": 0.25,
                    "comp": 0.25,
                },
                "alerting": {"score_threshold": 0.7, "max_alerts_per_run": 5},
            }
        )
    )


def test_missing_profile_errors_before_touching_sources(capsys, _isolated_home):
    _write_prefs(_isolated_home)

    rc = main(["discover"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert "profile" in err


def test_missing_prefs_errors(capsys, _isolated_home):
    _write_profile(_isolated_home, roles=["Staff Backend Engineer"])

    rc = main(["discover"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert "prefs init" in err


def test_no_usable_query_is_a_clean_noop(capsys, _isolated_home):
    """Empty profile roles and no `prefs.search` override → zero summary, exit 0."""
    _write_profile(_isolated_home, roles=[])
    _write_prefs(_isolated_home)

    rc = main(["discover"])

    assert rc == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert "fetched: 0   new: 0   seen: 0   skipped: 0" in out
    # No source was even attempted — nothing external happened.
    assert "sources:" not in out


def test_summary_run_id_matches_log_correlation_id(capsys, _isolated_home):
    """The run-id shown in the printed summary must be grep-able in the log.

    `main()` mints one correlation id (`obs.configure_run_logging()`) that
    every log line is stamped with; `run_discovery` must reuse that same id
    for `RunSummary.run_id` rather than minting its own (SC-005) — otherwise
    a user can't find their run's log lines from the id they were just shown.
    """
    _write_profile(_isolated_home, roles=[])
    _write_prefs(_isolated_home)

    rc = main(["discover"])

    assert rc == 0
    out, _err = capsys.readouterr()
    prefix, _, _rest = out.partition(" complete.")
    run_id = prefix.removeprefix("Discovery run ")

    from jobhunter import config

    log_text = config.log_path().read_text()
    assert f"[run={run_id}]" in log_text
    # Every line this invocation wrote carries the same correlation id.
    assert "[run=-]" not in log_text


def test_unknown_source_errors(capsys, _isolated_home):
    _write_profile(_isolated_home, roles=["Staff Backend Engineer"])
    _write_prefs(_isolated_home)

    rc = main(["discover", "--source", "bogus"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert "bogus" in err


def test_whole_run_failure_exits_nonzero(capsys, monkeypatch, _isolated_home):
    """An unexpected error (not a per-source SourceError) fails the whole run."""
    _write_profile(_isolated_home, roles=["Staff Backend Engineer"])
    _write_prefs(_isolated_home)

    def _boom(*args, **kwargs):
        raise RuntimeError("store unwritable")

    monkeypatch.setattr("jobhunter.discovery.run.run_discovery", _boom)

    rc = main(["discover"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")


def test_dry_run_writes_nothing_and_exits_zero(capsys, _isolated_home):
    _write_profile(_isolated_home, roles=[])
    _write_prefs(_isolated_home)

    rc = main(["discover", "--dry-run"])

    assert rc == 0
    out, _err = capsys.readouterr()
    assert "fetched: 0   new: 0   seen: 0   skipped: 0" in out
    assert not config.db_path().exists()
