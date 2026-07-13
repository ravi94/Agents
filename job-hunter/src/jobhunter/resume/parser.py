"""T015 [US1] — resume parsing orchestration.

Ties the pieces together: extract text → structure via the provider → persist
atomically. Only the extracted text reaches the provider (FR-014). Any failure
(unreadable PDF, provider error, invalid profile) propagates before the write,
so an existing ``profile.json`` is left byte-for-byte intact (FR-012).
"""

from __future__ import annotations

from pathlib import Path

from jobhunter import obs
from jobhunter.llm.provider import LLMProvider
from jobhunter.models.profile import Profile, save_profile
from jobhunter.resume.extract import extract_text


def parse_resume(pdf_path: str | Path, provider: LLMProvider) -> Profile:
    """Derive a :class:`Profile` from ``pdf_path`` and persist it atomically.

    Returns the validated, persisted profile. Raises before writing on any
    extraction or provider failure, leaving prior state untouched. The LLM call
    is traced (metadata only) per Constitution Principle VIII.
    """
    log = obs.get_logger("resume.parser")
    with obs.trace("resume.extract", source=Path(pdf_path).name):
        resume_text = extract_text(pdf_path)
    with obs.trace("llm.structure_resume", source=type(provider).__name__):
        profile = provider.structure_resume(resume_text)
    save_profile(profile)
    log.info("profile persisted skills=%d seniority=%s", len(profile.skills), profile.seniority)
    return profile
