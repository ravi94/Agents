"""T018 [US2] — integration test for the guided interview + reload (prefs/interview.py).

Exercises the one-time seeding flow end-to-end with mocked stdin: the interview
writes a schema-valid ``prefs.yaml``; it refuses to clobber an existing file
without ``--force``; an aborted interview writes nothing; and a hand-edited
value is honored on the next load *without* re-running the interview
(FR-007, FR-008). Written first (Constitution VII) — expected to fail until T020.
"""

from __future__ import annotations

import builtins

import pytest
import yaml

from jobhunter import config
from jobhunter.models.preferences import Preferences, load_preferences
from jobhunter.prefs.interview import run_interview

# The fixed answer sequence, in the order the interview asks its questions.
# (Mirrors the canonical prefs contract; drives the design of T020's prompts.)
INTERVIEW_ANSWERS = [
    "Bangalore, Remote",              # locations
    "remote, hybrid",                 # work_modes
    "product, gcc",                   # company_types_allow
    "services, staffing",             # company_types_deny
    "60",                             # comp_floor_lpa
    "senior",                         # seniority_floor
    "0.4",                            # soft_weights.work_life_balance
    "0.3",                            # soft_weights.stability
    "0.2",                            # soft_weights.scope
    "0.1",                            # soft_weights.comp
    "0.7",                            # alerting.score_threshold
    "10",                             # alerting.max_alerts_per_run
]


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


def _scripted_input(answers):
    """A stand-in for ``input()`` that replays canned answers in order."""
    it = iter(answers)

    def _input(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:  # pragma: no cover - signals a prompt/answer mismatch
            raise AssertionError(
                f"interview asked more questions than expected: {prompt!r}"
            ) from None

    return _input


def _aborting_input(*_args, **_kwargs):
    """Simulate the user interrupting the interview (Ctrl-C)."""
    raise KeyboardInterrupt


def test_interview_writes_schema_valid_prefs(monkeypatch):
    monkeypatch.setattr(builtins, "input", _scripted_input(INTERVIEW_ANSWERS))

    written = run_interview()

    assert written == config.prefs_path()
    assert written.exists()

    # The written file parses cleanly through the same validator every load uses.
    prefs = load_preferences(written)
    assert isinstance(prefs, Preferences)
    assert prefs.hard_filters.locations == ["Bangalore", "Remote"]
    assert prefs.hard_filters.work_modes == ["remote", "hybrid"]
    assert prefs.hard_filters.comp_floor_lpa == 60
    assert prefs.hard_filters.seniority_floor == "senior"
    assert prefs.alerting.max_alerts_per_run == 10


def test_init_refuses_to_overwrite_without_force(monkeypatch):
    config.prefs_path().parent.mkdir(parents=True, exist_ok=True)
    sentinel = "hand: crafted\n"
    config.prefs_path().write_text(sentinel)

    monkeypatch.setattr(builtins, "input", _scripted_input(INTERVIEW_ANSWERS))

    with pytest.raises(FileExistsError):
        run_interview(force=False)

    # The existing file is left byte-for-byte intact — no silent clobber.
    assert config.prefs_path().read_text() == sentinel


def test_force_overwrites_existing_prefs(monkeypatch):
    config.prefs_path().parent.mkdir(parents=True, exist_ok=True)
    config.prefs_path().write_text("hand: crafted\n")

    monkeypatch.setattr(builtins, "input", _scripted_input(INTERVIEW_ANSWERS))

    run_interview(force=True)

    prefs = load_preferences()
    assert prefs.hard_filters.locations == ["Bangalore", "Remote"]


def test_aborted_interview_writes_nothing(monkeypatch):
    monkeypatch.setattr(builtins, "input", _aborting_input)

    with pytest.raises(KeyboardInterrupt):
        run_interview()

    assert not config.prefs_path().exists()


def test_hand_edit_honored_on_reload_without_reinterview(monkeypatch):
    monkeypatch.setattr(builtins, "input", _scripted_input(INTERVIEW_ANSWERS))
    written = run_interview()

    # User hand-edits the file directly (FR-007).
    data = yaml.safe_load(written.read_text())
    data["hard_filters"]["comp_floor_lpa"] = 95
    data["hard_filters"]["locations"] = ["Hyderabad"]
    written.write_text(yaml.safe_dump(data))

    # Reloading just reads and validates — it never re-runs the interview,
    # so the edited values are honored verbatim.
    reloaded = load_preferences(written)
    assert reloaded.hard_filters.comp_floor_lpa == 95
    assert reloaded.hard_filters.locations == ["Hyderabad"]
