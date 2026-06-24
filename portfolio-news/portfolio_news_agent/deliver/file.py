"""File delivery: write the brief to a summary-<date>.md file instead of emailing."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from ..config import Config

log = logging.getLogger(__name__)


def write(cfg: Config, subject: str, text_body: str) -> Path:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.output_dir / f"summary-{date.today().isoformat()}.md"
    path.write_text(f"# {subject}\n\n{text_body.strip()}\n", encoding="utf-8")
    log.info("summary written to %s", path)
    return path
