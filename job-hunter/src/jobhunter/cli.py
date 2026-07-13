"""T006 — CLI skeleton for the jobhunter command.

Wires the three M1 commands (``profile``, ``prefs init|validate``, ``db init``)
to placeholder handlers per ``contracts/cli.md``. Real behavior arrives in the
per-story tasks (T016, T021, T025); for now handlers report that they are not
yet implemented. Conventions: errors go to stderr, success summaries to stdout,
and any failure exits non-zero.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path


class CommandError(Exception):
    """Raised by handlers to signal an actionable, user-facing failure."""


def _not_implemented(command: str):
    def handler(_args: argparse.Namespace) -> int:
        raise CommandError(f"'{command}' is not implemented yet")

    return handler


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
    p_prefs_init.set_defaults(func=_not_implemented("prefs init"))

    p_prefs_validate = prefs_sub.add_parser(
        "validate", help="Validate prefs.yaml against the schema."
    )
    p_prefs_validate.set_defaults(func=_not_implemented("prefs validate"))

    # db init  (US3 -> T025)
    p_db = subparsers.add_parser("db", help="Manage the SQLite job store (jobs.db).")
    db_sub = p_db.add_subparsers(dest="db_command", required=True)
    p_db_init = db_sub.add_parser("init", help="Create the job store if absent (idempotent).")
    p_db_init.set_defaults(func=_not_implemented("db init"))

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
