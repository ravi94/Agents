"""T011 [US1] — unit tests for work-mode classification (discovery/normalize.py).

Rules applied in order, first match wins (FR-009, contracts/source_mapping.md):
an explicit remote flag true → `remote`; else a case-insensitive keyword scan
of title+description text → `remote`/`hybrid`/`onsite`; no signal → `unknown`
(never guessed). Written first (Constitution VII) — expected to fail until
T016 implements `classify_work_mode`.
"""

from __future__ import annotations

import pytest

from jobhunter.discovery.normalize import classify_work_mode


def test_explicit_remote_flag_wins():
    assert classify_work_mode(explicit_remote=True, text="") == "remote"


def test_explicit_remote_flag_wins_over_conflicting_text():
    assert (
        classify_work_mode(explicit_remote=True, text="Onsite role, in-office required")
        == "remote"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Fully remote position",
        "Work from home role",
        "WFH friendly team",
        "This is a fully remote opportunity",
    ],
)
def test_text_signals_remote(text):
    assert classify_work_mode(explicit_remote=False, text=text) == "remote"


def test_text_signal_hybrid():
    assert (
        classify_work_mode(explicit_remote=False, text="Hybrid role, three days onsite")
        == "hybrid"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Onsite role in our Bangalore office",
        "On-site presence required",
        "In office five days a week",
        "In-office collaboration expected",
    ],
)
def test_text_signals_onsite(text):
    assert classify_work_mode(explicit_remote=False, text=text) == "onsite"


def test_no_signal_is_unknown_never_guessed():
    assert (
        classify_work_mode(explicit_remote=False, text="Join our growing engineering team.")
        == "unknown"
    )


def test_no_explicit_flag_and_no_text_is_unknown():
    assert classify_work_mode(explicit_remote=None, text="") == "unknown"


def test_classification_is_case_insensitive():
    assert classify_work_mode(explicit_remote=False, text="FULLY REMOTE ROLE") == "remote"
