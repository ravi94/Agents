"""T016 [US3] — whole-run-failure notification lives at the CLI seam, not in
`run_pipeline` (contracts/pipeline.md C7).

A `jobhunter run` that cannot complete (a missing precondition, or a stage
raising) must route to `obs.notify_error` and exit non-zero — but that ntfy is
`cli.main()`'s job. `run_pipeline` itself only raises; it never self-notifies
(per-role alerts remain `run_scoring`'s responsibility). These tests pin both
sides of that boundary.
"""

from __future__ import annotations

import pytest


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
