"""T005 — app data directory and file-path resolution.

All jobhunter state lives under a single app data directory: the default is
``~/.job-hunter/``, overridable via the ``JOBHUNTER_HOME`` environment variable
(which eases testing and lets users relocate their data). This module is the one
place that knows those locations; everything else derives paths from here.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

ENV_HOME = "JOBHUNTER_HOME"
DEFAULT_DIRNAME = ".job-hunter"

PROFILE_FILENAME = "profile.json"
PREFS_FILENAME = "prefs.yaml"
DB_FILENAME = "jobs.db"
LOGS_DIRNAME = "logs"
LOG_FILENAME = "jobhunter.log"
CACHE_DIRNAME = "cache"


def load_env() -> None:
    """Populate ``os.environ`` from a ``.env`` file, if one is found.

    Searches the current directory and its parents (``python-dotenv``'s
    default). Real environment variables always win — a value already set in
    the shell is never overridden by ``.env`` (lets `export FOO=bar` still
    take precedence for one-off overrides).
    """
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)


def get_home() -> Path:
    """Return the app data directory, honoring ``JOBHUNTER_HOME`` if set.

    Does not touch the filesystem; use :func:`ensure_home` when the directory
    must exist. ``~`` in an override is expanded.
    """
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_DIRNAME


def ensure_home() -> Path:
    """Return the app data directory, creating it (and parents) if absent."""
    home = get_home()
    home.mkdir(parents=True, exist_ok=True)
    return home


def profile_path() -> Path:
    """Path to the persisted structured profile (``profile.json``)."""
    return get_home() / PROFILE_FILENAME


def prefs_path() -> Path:
    """Path to the user preferences file (``prefs.yaml``)."""
    return get_home() / PREFS_FILENAME


def db_path() -> Path:
    """Path to the SQLite job store (``jobs.db``)."""
    return get_home() / DB_FILENAME


def logs_dir() -> Path:
    """Directory holding the (rotating) run logs."""
    return get_home() / LOGS_DIRNAME


def log_path() -> Path:
    """Path to the active run log file (``logs/jobhunter.log``)."""
    return logs_dir() / LOG_FILENAME


def cache_dir() -> Path:
    """Directory holding the file-based HTTP response cache (source fetches)."""
    return get_home() / CACHE_DIRNAME
