"""T020 [US2] — the one-time guided interview that seeds ``prefs.yaml``.

Asks a fixed set of questions, builds a :class:`Preferences`, validates it, then
writes ``prefs.yaml``. Guarantees: it refuses to clobber an existing file unless
``force`` is set (FR-007 — hand-edits are never silently overwritten), and an
aborted interview writes nothing at all. After seeding, the file is owned by the
user; reloading only ever reads and validates it.
"""

from __future__ import annotations

from pathlib import Path

from jobhunter import config
from jobhunter.models.preferences import Preferences, save_preferences


def _ask(prompt: str) -> str:
    return input(f"{prompt}: ").strip()


def _ask_list(prompt: str) -> list[str]:
    raw = _ask(f"{prompt} (comma-separated)")
    return [item.strip() for item in raw.split(",") if item.strip()]


def run_interview(force: bool = False, path: Path | None = None) -> Path:
    """Run the guided interview and write a validated ``prefs.yaml``.

    Raises :class:`FileExistsError` if the target already exists and ``force`` is
    not set (the existing file is left untouched). Any interruption
    (:class:`KeyboardInterrupt`/EOF) propagates before anything is written.
    """
    target = path or config.prefs_path()
    if target.exists() and not force:
        raise FileExistsError(
            f"{target} already exists — hand-edit it directly, or pass --force to "
            "re-run the interview and overwrite it"
        )

    hard_filters = {
        "locations": _ask_list("Preferred locations"),
        "work_modes": _ask_list("Work modes (remote, hybrid, onsite)"),
        "company_types_allow": _ask_list("Company types to prefer (allow)"),
        "company_types_deny": _ask_list("Company types to exclude (deny)"),
        "comp_floor_lpa": _ask("Minimum compensation (LPA)"),
        "seniority_floor": _ask("Seniority floor (junior/mid/senior/staff/principal)"),
    }
    soft_weights = {
        "work_life_balance": _ask("Weight: work-life balance (0-1)"),
        "stability": _ask("Weight: stability (0-1)"),
        "scope": _ask("Weight: scope (0-1)"),
        "comp": _ask("Weight: compensation (0-1)"),
    }
    alerting = {
        "score_threshold": _ask("Alert score threshold (0-1)"),
        "max_alerts_per_run": _ask("Max alerts per run"),
    }

    # Validate before writing so a bad answer never yields a half-written file.
    prefs = Preferences.model_validate(
        {
            "hard_filters": hard_filters,
            "soft_weights": soft_weights,
            "alerting": alerting,
        }
    )
    return save_preferences(prefs, target)
