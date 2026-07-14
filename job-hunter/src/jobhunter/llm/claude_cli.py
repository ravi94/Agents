"""T014 [US1] — the Claude Code CLI provider.

Structures resume text by invoking ``claude -p "<prompt>" --output-format json``
non-interactively (Constitution I: Pro-subscription auth, zero metered spend).
The outer JSON is the CLI's result wrapper; its ``result`` field holds the
model's answer, which we require to be the structured-profile JSON. Any
timeout, non-zero exit, or malformed/invalid output becomes an
:class:`LLMProviderError` so the parser leaves existing state untouched.
"""

from __future__ import annotations

import json
import os
import subprocess

from pydantic import ValidationError

from jobhunter.llm.provider import LLMProvider, LLMProviderError
from jobhunter.models.profile import Profile

_DEFAULT_TIMEOUT_S = 120

_PROMPT_TEMPLATE = """\
You are a resume-structuring function. Read the RESUME TEXT below and return a \
single JSON object describing the candidate. Output ONLY the JSON object — no \
prose, no code fences.

Rules:
- Fields: full_name (string|null), skills (array of strings, non-empty), \
experience (array of {{company, title, start|null, end|null, summary|null}}), \
seniority (one of junior|mid|senior|staff|principal, or null), roles (array of \
strings), total_years_experience (number|null), source_resume_filename \
(string), parsed_at (ISO-8601 date-time string).
- Never fabricate. If the resume gives no basis for a field, use null (or an \
empty array for list fields other than skills).
- Set source_resume_filename to "{filename}" and parsed_at to "{parsed_at}".

RESUME TEXT:
{resume_text}
"""

_RERANK_PROMPT_TEMPLATE = """\
You are a job-fit reviewer. Given the CANDIDATE PROFILE and the JOB POSTINGS \
below, write one short (1-2 sentence) qualitative fit reason per job. Output \
ONLY a single JSON object mapping each job's "id" to its reason string — no \
prose, no code fences, no extra keys.

CANDIDATE PROFILE:
skills: {skills}
roles: {roles}

JOB POSTINGS:
{jobs}
"""


class ClaudeCLIProvider(LLMProvider):
    """Structures resume text and re-ranks scored jobs via the local ``claude`` CLI."""

    def __init__(
        self,
        *,
        filename: str | None = None,
        parsed_at: str | None = None,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
        claude_bin: str = "claude",
    ) -> None:
        # filename/parsed_at are only needed for structure_resume — rerank
        # callers (e.g. the `score --rerank` CLI wiring) never set them.
        self._filename = filename
        self._parsed_at = parsed_at
        self._timeout_s = timeout_s
        self._claude_bin = claude_bin

    def structure_resume(self, resume_text: str) -> Profile:
        prompt = _PROMPT_TEMPLATE.format(
            filename=self._filename,
            parsed_at=self._parsed_at,
            resume_text=resume_text,
        )
        stdout = self._run_claude(prompt, action="structuring the resume")
        return self._parse_profile(stdout)

    def rerank(self, candidates: list[dict], profile: Profile) -> dict[str, str]:
        prompt = _RERANK_PROMPT_TEMPLATE.format(
            skills=", ".join(profile.skills),
            roles=", ".join(profile.roles) or "none listed",
            jobs=json.dumps(candidates, indent=2),
        )
        stdout = self._run_claude(prompt, action="reranking")
        return self._parse_reasons(stdout)

    def _run_claude(self, prompt: str, *, action: str) -> str:
        # Strip ANTHROPIC_API_KEY so the CLI uses the claude.ai (Pro) login and
        # never falls back to metered API billing (Constitution I/II). A stray
        # key in the user's shell otherwise makes `claude` refuse the login.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        try:
            completed = subprocess.run(
                [self._claude_bin, "-p", prompt, "--output-format", "json"],
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                env=env,
            )
        except FileNotFoundError as exc:
            raise LLMProviderError(
                f"'{self._claude_bin}' not found — install the Claude Code CLI and log in."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMProviderError(
                f"claude timed out after {self._timeout_s}s while {action}."
            ) from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
            raise LLMProviderError(f"claude exited {completed.returncode}: {detail}")

        return completed.stdout

    def _parse_profile(self, stdout: str) -> Profile:
        try:
            wrapper = json.loads(stdout)
            inner = wrapper["result"] if isinstance(wrapper, dict) else wrapper
            payload = json.loads(inner) if isinstance(inner, str) else inner
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LLMProviderError(f"could not parse claude JSON output: {exc}") from exc

        try:
            return Profile.model_validate(payload)
        except ValidationError as exc:
            raise LLMProviderError(f"claude output failed profile validation: {exc}") from exc

    def _parse_reasons(self, stdout: str) -> dict[str, str]:
        try:
            wrapper = json.loads(stdout)
            inner = wrapper["result"] if isinstance(wrapper, dict) else wrapper
            payload = json.loads(inner) if isinstance(inner, str) else inner
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LLMProviderError(f"could not parse claude JSON output: {exc}") from exc

        if not isinstance(payload, dict) or not all(
            isinstance(job_id, str) and isinstance(reason, str)
            for job_id, reason in payload.items()
        ):
            raise LLMProviderError("claude rerank output was not a job id -> reason mapping")

        return payload
