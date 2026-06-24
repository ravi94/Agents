"""Save the final answer to a markdown file under reports/."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def _slugify(text: str, max_len: int = 60) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return (text or "report")[:max_len]


def save_report(question: str, answer_markdown: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    slug = _slugify(question)
    path = out_dir / f"{stamp}_{slug}.md"

    header = (
        f"---\n"
        f"question: {question!r}\n"
        f"generated_at: {datetime.now().isoformat(timespec='seconds')}\n"
        f"---\n\n"
    )
    path.write_text(header + answer_markdown.strip() + "\n", encoding="utf-8")
    return path
