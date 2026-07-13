"""T011 [US1] — raw text extraction from a resume PDF.

Pulls the text layer out of a PDF with ``pypdf``. Image-only (scanned) resumes
have no text layer; rather than send an empty prompt to the LLM, we raise a
clear, typed error so the parser refuses before any provider call (FR-012).
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

# Below this many non-whitespace characters we treat the PDF as effectively
# text-free (e.g. a scanned image) and refuse rather than call the LLM.
_MIN_MEANINGFUL_CHARS = 20


class ResumeExtractionError(Exception):
    """The resume PDF could not be read, or yielded no usable text."""


def extract_text(path: str | Path) -> str:
    """Return the extracted text of the resume PDF at ``path``.

    Accepts a ``Path`` or a raw path string (the CLI passes a string). Raises
    :class:`ResumeExtractionError` if the file is unreadable or has no text
    layer (image-only / scanned).
    """
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise ResumeExtractionError(f"resume file not found: {pdf_path}")

    try:
        reader = PdfReader(pdf_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except (PdfReadError, OSError, ValueError) as exc:
        raise ResumeExtractionError(f"could not read PDF text from {pdf_path}: {exc}") from exc

    if len(text.strip()) < _MIN_MEANINGFUL_CHARS:
        raise ResumeExtractionError(
            f"no extractable text in {pdf_path} — the resume appears to be an "
            "image-only/scanned PDF; provide a text-based PDF."
        )
    return text
