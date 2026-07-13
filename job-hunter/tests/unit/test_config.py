"""T007 — unit tests for app data directory + path resolution (config.py).

Covers default `~/.job-hunter/` location vs. `JOBHUNTER_HOME` override, the
derived file paths (profile.json / prefs.yaml / jobs.db), and directory
creation. Written first (Constitution VII) — expected to fail until T005.
"""

from pathlib import Path

from jobhunter import config


def test_home_defaults_to_dot_job_hunter(monkeypatch):
    monkeypatch.delenv("JOBHUNTER_HOME", raising=False)
    assert config.get_home() == Path.home() / ".job-hunter"


def test_home_honors_env_override(monkeypatch, tmp_path):
    override = tmp_path / "custom-home"
    monkeypatch.setenv("JOBHUNTER_HOME", str(override))
    assert config.get_home() == override


def test_home_expands_user_in_override(monkeypatch):
    monkeypatch.setenv("JOBHUNTER_HOME", "~/some-job-hunter")
    assert config.get_home() == Path.home() / "some-job-hunter"


def test_file_paths_live_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))
    assert config.profile_path() == tmp_path / "profile.json"
    assert config.prefs_path() == tmp_path / "prefs.yaml"
    assert config.db_path() == tmp_path / "jobs.db"


def test_ensure_home_creates_directory(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "job-hunter"
    monkeypatch.setenv("JOBHUNTER_HOME", str(target))
    assert not target.exists()

    returned = config.ensure_home()

    assert returned == target
    assert target.is_dir()


def test_ensure_home_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path / "h"))
    first = config.ensure_home()
    second = config.ensure_home()  # must not raise on an existing dir
    assert first == second and first.is_dir()
