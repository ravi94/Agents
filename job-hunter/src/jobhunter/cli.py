"""T006 — CLI for the jobhunter command.

Wires the three M1 commands (``profile``, ``prefs init|validate``, ``db init``)
to their handlers per ``contracts/cli.md`` (implemented in T016, T021, T025).
Conventions: errors go to stderr, success summaries to stdout, and any failure
exits non-zero.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path


class CommandError(Exception):
    """Raised by handlers to signal an actionable, user-facing failure."""


def _profile_handler(args: argparse.Namespace) -> int:
    """Derive and persist the structured profile from a resume PDF (US1)."""
    # Imported lazily so unrelated commands don't pay the pydantic/pypdf cost.
    from jobhunter.llm.claude_cli import ClaudeCLIProvider
    from jobhunter.llm.provider import LLMProviderError
    from jobhunter.resume.extract import ResumeExtractionError
    from jobhunter.resume.parser import parse_resume

    resume_path = Path(args.resume)
    provider = ClaudeCLIProvider(
        filename=resume_path.name,
        parsed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    try:
        profile = parse_resume(resume_path, provider)
    except (ResumeExtractionError, LLMProviderError) as exc:
        raise CommandError(str(exc)) from exc

    from jobhunter import config

    written = config.profile_path()
    seniority = profile.seniority or "unknown"
    roles = ", ".join(profile.roles) if profile.roles else "none detected"
    print(
        f"Profile written to {written}\n"
        f"  skills: {len(profile.skills)}\n"
        f"  seniority: {seniority}\n"
        f"  roles: {roles}"
    )
    return 0


def _format_validation_error(exc) -> str:
    """Render a pydantic ValidationError as field-named, log-free text (FR-013)."""
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
    )


def _prefs_init_handler(args: argparse.Namespace) -> int:
    """Run the guided interview and write prefs.yaml (US2)."""
    from pydantic import ValidationError

    from jobhunter import obs
    from jobhunter.prefs.interview import run_interview

    try:
        with obs.trace("prefs.interview"):
            written = run_interview(force=args.force)
    except FileExistsError as exc:
        raise CommandError(str(exc)) from exc
    except ValidationError as exc:
        raise CommandError(f"invalid answer(s): {_format_validation_error(exc)}") from exc
    except (KeyboardInterrupt, EOFError):
        # Aborted before completion — nothing was written (contract).
        print("\nprefs init aborted — no changes written.", file=sys.stderr)
        return 1

    print(
        f"Preferences written to {written}\n"
        f"  This file is yours to hand-edit; re-run 'prefs init --force' to redo the interview."
    )
    return 0


def _prefs_validate_handler(args: argparse.Namespace) -> int:
    """Validate prefs.yaml, surfacing weight-sum drift as a warning (US2)."""
    import warnings

    from pydantic import ValidationError

    from jobhunter import config, obs
    from jobhunter.models.preferences import load_preferences

    path = config.prefs_path()
    if not path.exists():
        raise CommandError(f"{path} not found — run 'jobhunter prefs init' first")

    try:
        with obs.trace("prefs.validate"), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            load_preferences(path)
    except ValidationError as exc:
        # Name the offending field(s) so the user can fix it without logs (FR-013).
        raise CommandError(f"invalid {path}: {_format_validation_error(exc)}") from exc

    for warning in caught:
        print(f"warning: {warning.message}", file=sys.stderr)
    print(f"{path} is valid.")
    return 0


def _db_init_handler(_args: argparse.Namespace) -> int:
    """Create the durable SQLite job store if absent, idempotently (US3)."""
    from jobhunter import obs
    from jobhunter.store import db

    with obs.trace("db.init"):
        path = db.init_db()

    print(f"Job store ready at {path}\n  schema version: {db.SCHEMA_VERSION}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobhunter",
        description="Local resume/profile/preferences copilot foundation (M1).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # profile <resume.pdf>  (US1 -> T016)
    p_profile = subparsers.add_parser(
        "profile", help="Derive and persist the structured profile from a resume PDF."
    )
    p_profile.add_argument("resume", metavar="resume.pdf", help="Path to a text-extractable PDF.")
    p_profile.set_defaults(func=_profile_handler)

    # prefs init|validate  (US2 -> T021)
    p_prefs = subparsers.add_parser("prefs", help="Manage user preferences (prefs.yaml).")
    prefs_sub = p_prefs.add_subparsers(dest="prefs_command", required=True)

    p_prefs_init = prefs_sub.add_parser(
        "init", help="Run the one-time guided interview and write prefs.yaml."
    )
    p_prefs_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing prefs.yaml (protects hand-edits otherwise).",
    )
    p_prefs_init.set_defaults(func=_prefs_init_handler)

    p_prefs_validate = prefs_sub.add_parser(
        "validate", help="Validate prefs.yaml against the schema."
    )
    p_prefs_validate.set_defaults(func=_prefs_validate_handler)

    # db init  (US3 -> T025)
    p_db = subparsers.add_parser("db", help="Manage the SQLite job store (jobs.db).")
    db_sub = p_db.add_subparsers(dest="db_command", required=True)
    p_db_init = db_sub.add_parser("init", help="Create the job store if absent (idempotent).")
    p_db_init.set_defaults(func=_db_init_handler)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Observability (Constitution Principle VIII): every run gets a correlation
    # id, a rotating log, and an ntfy error signal on failure.
    from jobhunter import obs

    run_id = obs.configure_run_logging()
    log = obs.get_logger("cli")
    log.info("run start command=%s run_id=%s", args.command, run_id)
    try:
        rc = args.func(args)
        log.info("run end command=%s exit=%s", args.command, rc)
        return rc
    except CommandError as exc:
        log.error("run failed command=%s error=%s", args.command, type(exc).__name__)
        obs.notify_error(f"jobhunter {args.command} failed: {exc}")
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
