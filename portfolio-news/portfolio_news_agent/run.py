"""Entry point the scheduler calls. `python -m portfolio_news_agent.run [--dry-run]`."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import brief as brief_mod
from .agent_loop import run_agent
from .config import load_config
from .deliver import email
from .deliver import file as file_deliver


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Portfolio News Agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the brief to stdout instead of emailing it.",
    )
    parser.add_argument(
        "--holdings",
        metavar="PATH",
        help="Holdings YAML file to load (overrides the HOLDINGS_FILE env var).",
    )
    args = parser.parse_args(argv)

    _setup_logging()
    log = logging.getLogger("portfolio_news_agent")

    try:
        cfg = load_config(Path(args.holdings) if args.holdings else None)
        if not args.dry_run and cfg.delivery_mode == "email":
            cfg.validate_for_email()  # fail fast before spending an agent run

        brief_text = run_agent(cfg)
        subject = brief_mod.subject()
        html_body = brief_mod.to_html(brief_text)
        text_body = brief_mod.to_plaintext(brief_text)

        if args.dry_run:
            print("=" * 60)
            print(subject)
            print("=" * 60)
            print(text_body)
            return 0

        if cfg.delivery_mode == "file":
            path = file_deliver.write(cfg, subject, text_body)
            log.info("summary saved to %s", path)
        else:
            email.send(cfg, subject, html_body, text_body)
        return 0
    except Exception:
        log.exception("run failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
