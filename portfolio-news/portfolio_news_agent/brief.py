"""Render the model's final brief (prose) into HTML + plaintext for email."""
from __future__ import annotations

import html
import re
from datetime import date

_URL_RE = re.compile(r"(https?://[^\s<>\")]+)")


def subject() -> str:
    return f"Portfolio Brief — {date.today().isoformat()}"


def to_plaintext(brief: str) -> str:
    return brief.strip() + "\n"


def to_html(brief: str) -> str:
    """Escape, linkify URLs, and turn blank-line-separated blocks into paragraphs."""
    blocks = re.split(r"\n\s*\n", brief.strip())
    parts: list[str] = []
    for block in blocks:
        escaped = html.escape(block)
        escaped = escaped.replace("\n", "<br>")
        linked = _URL_RE.sub(r'<a href="\1">\1</a>', escaped)
        parts.append(f"<p>{linked}</p>")
    body = "\n".join(parts)
    return f"""\
<!DOCTYPE html>
<html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;
 line-height:1.5; color:#1a1a1a; max-width:640px; margin:0 auto;">
<h2 style="border-bottom:1px solid #ddd; padding-bottom:8px;">{html.escape(subject())}</h2>
{body}
</body></html>
"""
