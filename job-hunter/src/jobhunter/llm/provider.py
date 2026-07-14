"""T013 [US1] — the LLMProvider swap seam.

All text-generation goes through :class:`LLMProvider` so the concrete backend
(Claude Code CLI for the MVP; local Ollama as the committed fast-follow) is a
later, isolated change (Constitution I). Only extracted resume text crosses this
boundary — never the file path or filename (FR-014).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from jobhunter.models.profile import Profile


class LLMProviderError(Exception):
    """A provider failed to produce a valid structured profile.

    Covers timeouts, non-zero exits, and malformed/invalid JSON — anything that
    means the parser must not write and must leave any existing profile intact.
    """


class LLMProvider(ABC):
    """Structures raw resume text into a validated :class:`Profile`."""

    @abstractmethod
    def structure_resume(self, resume_text: str) -> Profile:
        """Return a validated :class:`Profile` for ``resume_text``.

        Raises :class:`LLMProviderError` on any failure to produce one.
        """
        raise NotImplementedError

    @abstractmethod
    def rerank(self, candidates: list[dict], profile: Profile) -> dict[str, str]:
        """Return a ``{job_id: reason}`` mapping for the given candidates.

        ``candidates`` carries only ``id``/``title``/``description``/
        ``matched_skills`` per job — never ``prefs.yaml`` content or tracking
        state (Constitution I). Called at most once per re-rank pass (the
        caller, ``scoring/rerank.py``, is responsible for bounding
        ``candidates`` to the top ~25 before calling). Raises
        :class:`LLMProviderError` on any failure to produce a valid mapping.
        """
        raise NotImplementedError
