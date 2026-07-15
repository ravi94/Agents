"""T016 [US3] — whole-run-failure notification lives at the CLI seam, not in
`run_pipeline` (contracts/pipeline.md C7).

A `jobhunter run` that cannot complete (a missing precondition, or a stage
raising) must route to `obs.notify_error` and exit non-zero — but that ntfy is
`cli.main()`'s job. `run_pipeline` itself only raises; it never self-notifies
(per-role alerts remain `run_scoring`'s responsibility). These tests pin both
sides of that boundary.
"""

from __future__ import annotations

import shutil

import pytest


def _seed_profile_and_prefs(fixtures_dir) -> None:
    """Copy the valid fixture profile/prefs into the active JOBHUNTER_HOME."""
    from jobhunter import config

    config.ensure_home()
    shutil.copy(fixtures_dir / "scoring_profile.json", config.profile_path())
    shutil.copy(fixtures_dir / "scoring_prefs.yaml", config.prefs_path())


def test_missing_profile_notifies_error_and_exits_nonzero(monkeypatch, tmp_path):
    """A run with no persisted profile fails fast: `cli.main()` catches the
    error, fires one ntfy error signal, and returns non-zero."""
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))  # empty home — no profile

    from jobhunter import cli, obs

    errors: list[str] = []
    monkeypatch.setattr(obs, "notify_error", lambda message, **kwargs: errors.append(message))

    rc = cli.main(["run"])

    assert rc != 0
    assert len(errors) == 1  # exactly one whole-run failure signal


def test_run_pipeline_raises_and_never_self_notifies(monkeypatch):
    """A stage error propagates out of `run_pipeline` unchanged, and
    `run_pipeline` sends no ntfy of its own — the CLI owns that (C7)."""
    from jobhunter import obs
    from jobhunter.pipeline import run as pipeline_run

    def boom(*args, **kwargs):
        raise RuntimeError("store unwritable")

    monkeypatch.setattr(pipeline_run, "run_discovery", boom)

    errors: list[str] = []
    monkeypatch.setattr(obs, "notify_error", lambda message, **kwargs: errors.append(message))

    with pytest.raises(RuntimeError, match="store unwritable"):
        pipeline_run.run_pipeline([], object(), object())

    assert errors == []  # run_pipeline never self-notifies


# --------------------------------------------------------------------------- #
# T022 [Polish] — CLI error / exit-code contract for `run`
# (contracts/cli.md). Missing prereqs and an unknown source fail non-zero; a
# clean no-op run (nothing to discover, nothing new to score) exits 0.
# --------------------------------------------------------------------------- #


def test_missing_prefs_exits_nonzero(monkeypatch, tmp_path, fixtures_dir):
    """A profile but no `prefs.yaml` still fails fast, non-zero."""
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))

    from jobhunter import cli, config

    config.ensure_home()
    shutil.copy(fixtures_dir / "scoring_profile.json", config.profile_path())
    # prefs.yaml deliberately absent.

    assert cli.main(["run"]) != 0


def test_unknown_source_exits_nonzero(monkeypatch, tmp_path, fixtures_dir):
    """An unknown `--source` name is rejected, non-zero — before any fetch."""
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))
    _seed_profile_and_prefs(fixtures_dir)

    from jobhunter import cli

    assert cli.main(["run", "--source", "nope"]) != 0


def test_clean_no_op_run_exits_zero(monkeypatch, tmp_path, fixtures_dir):
    """A run with valid prereqs, sources that return nothing, and an empty
    store is a clean no-op: it completes and exits 0."""
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))
    _seed_profile_and_prefs(fixtures_dir)

    from fixtures.fake_sources import FakeJobSource

    # Swap the real source factories for empty fakes so no live call is made;
    # _run_handler resolves these names at call time (module-qualified).
    monkeypatch.setattr(
        "jobhunter.sources.jsearch.JSearchSource", lambda: FakeJobSource([], name="jsearch")
    )
    monkeypatch.setattr(
        "jobhunter.sources.adzuna.AdzunaSource", lambda: FakeJobSource([], name="adzuna")
    )

    from jobhunter import cli

    assert cli.main(["run"]) == 0
