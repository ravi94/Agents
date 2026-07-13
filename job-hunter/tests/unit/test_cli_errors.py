"""T027 — CLI error/exit-code behavior across all three M1 commands.

Locks the contract from ``contracts/cli.md``: failures print an actionable
message to **stderr** (never stdout) and exit **non-zero**, while successes go
to stdout and exit ``0``. These cover the failure paths that don't need a live
``claude`` call — an unreadable resume, a missing/existing/invalid prefs file,
and argparse-level usage errors — so a regression in exit codes or stream
routing fails fast.
"""

from __future__ import annotations

import pytest

from jobhunter.cli import main

FIXTURES = "tests/fixtures"


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    """Every command resolves state under a throwaway JOBHUNTER_HOME."""
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------- #
# profile — unreadable / missing PDF (fails before any provider call, FR-012)
# --------------------------------------------------------------------------- #


def test_profile_image_only_pdf_errors_without_write(capsys, _isolated_home):
    """A scanned/image-only PDF errors on stderr, exits non-zero, writes nothing."""
    existing = _isolated_home / "profile.json"
    existing.write_text('{"sentinel": true}')

    rc = main(["profile", f"{FIXTURES}/scanned_image.pdf"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""  # no success summary leaked to stdout
    assert err.startswith("error: ")
    assert "image-only" in err or "no extractable text" in err
    # Existing profile is left untouched — no partial/clobbered write.
    assert existing.read_text() == '{"sentinel": true}'


def test_profile_missing_file_errors(capsys):
    rc = main(["profile", f"{FIXTURES}/does_not_exist.pdf"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert "not found" in err


# --------------------------------------------------------------------------- #
# prefs init — refuses to clobber an existing file without --force
# --------------------------------------------------------------------------- #


def test_prefs_init_refuses_existing_without_force(capsys, _isolated_home):
    prefs = _isolated_home / "prefs.yaml"
    sentinel = "hand: crafted\n"
    prefs.write_text(sentinel)

    rc = main(["prefs", "init"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    # The hand-edited file is preserved byte-for-byte.
    assert prefs.read_text() == sentinel


# --------------------------------------------------------------------------- #
# prefs validate — missing file, and a field-named validation error
# --------------------------------------------------------------------------- #


def test_prefs_validate_missing_file_errors(capsys, _isolated_home):
    rc = main(["prefs", "validate"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert "prefs init" in err  # points the user at the fix


def test_prefs_validate_invalid_field_names_offender(capsys, _isolated_home):
    """An out-of-enum value errors non-zero and names the offending field (FR-013)."""
    prefs = _isolated_home / "prefs.yaml"
    prefs.write_text(
        "hard_filters:\n"
        "  locations: [Bangalore]\n"
        "  work_modes: [teleport]\n"  # not a valid work mode
        "  comp_floor_lpa: 60\n"
        "  seniority_floor: senior\n"
        "soft_weights:\n"
        "  work_life_balance: 0.4\n"
        "  stability: 0.3\n"
        "  scope: 0.2\n"
        "  comp: 0.1\n"
        "alerting:\n"
        "  score_threshold: 0.7\n"
        "  max_alerts_per_run: 10\n"
    )

    rc = main(["prefs", "validate"])

    assert rc != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("error: ")
    assert "work_modes" in err  # the message names the bad field


# --------------------------------------------------------------------------- #
# db init — the happy path is exit 0 with the summary on stdout (contrast case)
# --------------------------------------------------------------------------- #


def test_db_init_succeeds_to_stdout(capsys, _isolated_home):
    rc = main(["db", "init"])

    assert rc == 0
    out, err = capsys.readouterr()
    assert "Job store ready" in out
    assert err == ""


# --------------------------------------------------------------------------- #
# argparse usage errors — missing (sub)command exits non-zero, message on stderr
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "argv",
    [
        [],                 # no command at all
        ["prefs"],          # subcommand required
        ["db"],             # subcommand required
        ["bogus"],          # unknown command
    ],
)
def test_usage_errors_exit_nonzero(capsys, argv):
    with pytest.raises(SystemExit) as excinfo:
        main(argv)

    assert excinfo.value.code != 0
    _out, err = capsys.readouterr()
    assert err  # argparse prints usage/error to stderr
