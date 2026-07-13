"""T008 [US1] — unit tests for PDF text extraction (resume/extract.py).

`extract_text` must pull text from a text-extractable resume PDF and raise a
clear, typed error for an image-only (scanned) PDF where no text is present —
so the parser can refuse before any LLM call (FR-012). Written first
(Constitution VII) — expected to fail until T011.
"""

import pytest

from jobhunter.resume.extract import ResumeExtractionError, extract_text


def test_extracts_text_from_sample_resume(sample_resume_pdf):
    text = extract_text(sample_resume_pdf)

    assert isinstance(text, str)
    assert text.strip(), "expected non-empty extracted text"


def test_accepts_path_as_string(sample_resume_pdf):
    # Callers (CLI) pass a raw path string; it must be accepted like a Path.
    assert extract_text(str(sample_resume_pdf)).strip()


def test_image_only_pdf_raises_clear_error(scanned_image_pdf):
    with pytest.raises(ResumeExtractionError) as excinfo:
        extract_text(scanned_image_pdf)

    # Error must be actionable — it names the extraction/text problem.
    assert "text" in str(excinfo.value).lower()


def test_missing_file_raises(tmp_path):
    with pytest.raises((ResumeExtractionError, FileNotFoundError)):
        extract_text(tmp_path / "does_not_exist.pdf")
