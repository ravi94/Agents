"""T006 — CLI for the jobhunter command.

Wires the M1 commands (``profile``, ``prefs init|validate``, ``db init``) and
the M2 ``discover`` command to their handlers per ``contracts/cli.md``.
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


def _discover_handler(args: argparse.Namespace) -> int:
    """Query sources, normalize, dedup, and persist new jobs (M2, US1-3)."""
    from pydantic import ValidationError

    from jobhunter import config, obs
    from jobhunter.discovery.run import run_discovery
    from jobhunter.models.preferences import load_preferences
    from jobhunter.models.profile import load_profile
    from jobhunter.sources.adzuna import AdzunaSource
    from jobhunter.sources.jsearch import JSearchSource

    profile_path = config.profile_path()
    if not profile_path.exists():
        raise CommandError(f"{profile_path} not found — run 'jobhunter profile <resume.pdf>' first")
    prefs_path = config.prefs_path()
    if not prefs_path.exists():
        raise CommandError(f"{prefs_path} not found — run 'jobhunter prefs init' first")

    try:
        profile = load_profile(profile_path)
    except (ValidationError, ValueError) as exc:
        raise CommandError(f"invalid {profile_path}: {exc}") from exc
    try:
        prefs = load_preferences(prefs_path)
    except ValidationError as exc:
        raise CommandError(f"invalid {prefs_path}: {_format_validation_error(exc)}") from exc

    # Registration = one factory entry per source (FR-002).
    source_factories = {"jsearch": JSearchSource, "adzuna": AdzunaSource}
    selected_names = args.source or list(source_factories)
    unknown = [name for name in selected_names if name not in source_factories]
    if unknown:
        raise CommandError(f"unknown source(s): {', '.join(unknown)}")
    sources = [source_factories[name]() for name in selected_names]

    with obs.trace("discover.run"):
        summary = run_discovery(sources, profile, prefs, dry_run=args.dry_run)

    lines = [
        f"Discovery run {summary.run_id} complete.",
        f"  fetched: {summary.fetched}   new: {summary.new}   "
        f"seen: {summary.seen}   skipped: {summary.skipped}",
    ]
    if summary.attempted_sources:
        lines.append("  sources:")
        for name in summary.attempted_sources:
            failure = summary.source_failures.get(name)
            status = f"failed  {failure}" if failure else "ok"
            lines.append(f"    {name}  {status}")
    print("\n".join(lines))
    return 0


def _score_handler(args: argparse.Namespace) -> int:
    """Filter, score, and persist every `state='new'` job (M3, US1 -> T015)."""
    from pydantic import ValidationError

    from jobhunter import config, obs
    from jobhunter.llm.claude_cli import ClaudeCLIProvider
    from jobhunter.models.preferences import load_preferences
    from jobhunter.models.profile import load_profile
    from jobhunter.scoring.run import run_scoring
    from jobhunter.scoring.scorer import format_breakdown

    profile_path = config.profile_path()
    if not profile_path.exists():
        raise CommandError(f"{profile_path} not found — run 'jobhunter profile <resume.pdf>' first")
    prefs_path = config.prefs_path()
    if not prefs_path.exists():
        raise CommandError(f"{prefs_path} not found — run 'jobhunter prefs init' first")

    try:
        profile = load_profile(profile_path)
    except (ValidationError, ValueError) as exc:
        raise CommandError(f"invalid {profile_path}: {exc}") from exc
    try:
        prefs = load_preferences(prefs_path)
    except ValidationError as exc:
        raise CommandError(f"invalid {prefs_path}: {_format_validation_error(exc)}") from exc

    # --rerank is a strict opt-in addition (US4): base scoring never calls an
    # LLM, so the provider is only constructed when the flag is passed.
    provider = ClaudeCLIProvider() if args.rerank else None
    with obs.trace("score.run"):
        summary = run_scoring(
            profile, prefs, dry_run=args.dry_run, rerank=args.rerank, provider=provider
        )

    lines = [
        f"Scoring run {summary.run_id} complete.",
        f"  filtered_out: {summary.filtered_out}   scored: {summary.scored}   "
        f"alerted: {summary.alerted}   reranked: {summary.reranked}",
    ]
    if summary.top_breakdown is not None:
        lines.append(
            f"  top: {summary.top_job_title!r} — {format_breakdown(summary.top_breakdown)}"
        )
    print("\n".join(lines))
    return 0


def _run_handler(args: argparse.Namespace) -> int:
    """Run the whole pipeline end to end: discover then score (M4, US1)."""
    from pydantic import ValidationError

    from jobhunter import config, obs
    from jobhunter.llm.claude_cli import ClaudeCLIProvider
    from jobhunter.models.preferences import load_preferences
    from jobhunter.models.profile import load_profile
    from jobhunter.pipeline.run import format_pipeline_summary, run_pipeline
    from jobhunter.sources.adzuna import AdzunaSource
    from jobhunter.sources.jsearch import JSearchSource

    profile_path = config.profile_path()
    if not profile_path.exists():
        raise CommandError(f"{profile_path} not found — run 'jobhunter profile <resume.pdf>' first")
    prefs_path = config.prefs_path()
    if not prefs_path.exists():
        raise CommandError(f"{prefs_path} not found — run 'jobhunter prefs init' first")

    try:
        profile = load_profile(profile_path)
    except (ValidationError, ValueError) as exc:
        raise CommandError(f"invalid {profile_path}: {exc}") from exc
    try:
        prefs = load_preferences(prefs_path)
    except ValidationError as exc:
        raise CommandError(f"invalid {prefs_path}: {_format_validation_error(exc)}") from exc

    # Registration = one factory entry per source (FR-002); same registry as
    # `discover`. Scoring is unaffected by --source (it scores whatever is new).
    source_factories = {"jsearch": JSearchSource, "adzuna": AdzunaSource}
    selected_names = args.source or list(source_factories)
    unknown = [name for name in selected_names if name not in source_factories]
    if unknown:
        raise CommandError(f"unknown source(s): {', '.join(unknown)}")
    sources = [source_factories[name]() for name in selected_names]

    # --rerank is a strict opt-in addition: the pipeline never calls a
    # text-generation LLM otherwise, so the provider is built only when set
    # (mirrors `_score_handler`).
    provider = ClaudeCLIProvider() if args.rerank else None
    with obs.trace("pipeline.run"):
        summary = run_pipeline(
            sources, profile, prefs, dry_run=args.dry_run, rerank=args.rerank, provider=provider
        )

    print(format_pipeline_summary(summary, dry_run=args.dry_run))
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

    # discover [--source NAME]... [--dry-run]  (M2 US1-3 -> T021)
    p_discover = subparsers.add_parser(
        "discover", help="Query sources, normalize, dedup, and persist new jobs."
    )
    p_discover.add_argument(
        "--source",
        action="append",
        metavar="NAME",
        help="Restrict the run to this source (repeatable). Default: all configured sources.",
    )
    p_discover.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch, normalize, and dedup, but write nothing to the store.",
    )
    p_discover.set_defaults(func=_discover_handler)

    # score [--dry-run]  (M3 US1 -> T015)
    p_score = subparsers.add_parser(
        "score", help="Filter and score every state='new' job against profile/prefs."
    )
    p_score.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute filters/scores/alerts, but write nothing to the store.",
    )
    p_score.add_argument(
        "--rerank",
        action="store_true",
        help=(
            "After scoring, send the top ~25 scored survivors through one "
            "bounded LLM call for a qualitative fit reason. Omitted by "
            "default — base scoring never calls an LLM."
        ),
    )
    p_score.set_defaults(func=_score_handler)

    # run [--source NAME]... [--dry-run] [--rerank]  (M4 US1 -> T010)
    p_run = subparsers.add_parser(
        "run",
        help="Run the whole pipeline: discover then score, under one run id.",
    )
    p_run.add_argument(
        "--source",
        action="append",
        metavar="NAME",
        help="Restrict discovery to this source (repeatable). Default: all configured sources.",
    )
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Rehearse the full pipeline: compute counts but write nothing and send no alert.",
    )
    p_run.add_argument(
        "--rerank",
        action="store_true",
        help=(
            "After scoring, send the top ~25 scored survivors through one "
            "bounded LLM call for a qualitative fit reason. Omitted by "
            "default — the pipeline never calls an LLM otherwise."
        ),
    )
    p_run.set_defaults(func=_run_handler)

    # db init  (US3 -> T025)
    p_db = subparsers.add_parser("db", help="Manage the SQLite job store (jobs.db).")
    db_sub = p_db.add_subparsers(dest="db_command", required=True)
    p_db_init = db_sub.add_parser("init", help="Create the job store if absent (idempotent).")
    p_db_init.set_defaults(func=_db_init_handler)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    from jobhunter import config

    config.load_env()

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
    except Exception as exc:  # noqa: BLE001 — an unexpected failure still gets an ntfy signal
        log.error("run failed command=%s error=%s", args.command, type(exc).__name__)
        obs.notify_error(f"jobhunter {args.command} failed unexpectedly: {type(exc).__name__}")
        print(f"error: unexpected failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
