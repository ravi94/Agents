"""Unit tests for the Claude CLI provider (llm/claude_cli.py).

The MVP is committed to the Pro-subscription login with zero metered spend
(Constitution I/II). A stray ``ANTHROPIC_API_KEY`` in the user's shell makes the
CLI refuse the claude.ai login, so the provider must strip it from the
subprocess environment — guaranteeing the subscription auth is used and no API
key is ever billed.
"""

import json

import pytest

from jobhunter.llm.claude_cli import ClaudeCLIProvider
from jobhunter.llm.provider import LLMProviderError


@pytest.fixture
def provider() -> ClaudeCLIProvider:
    return ClaudeCLIProvider(filename="sample_resume.pdf", parsed_at="2026-07-13T00:00:00Z")


def test_strips_anthropic_api_key_from_subprocess_env(
    provider, profile_payload, claude_response, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-removed")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")

        class Result:
            returncode = 0
            stdout = json.dumps(claude_response)
            stderr = ""

        return Result()

    monkeypatch.setattr("jobhunter.llm.claude_cli.subprocess.run", fake_run)

    profile = provider.structure_resume("some resume text")

    assert profile.skills  # parsed the fixture response
    assert "ANTHROPIC_API_KEY" not in captured["env"]
    # Other environment is preserved (the CLI still needs PATH, HOME, etc.).
    assert "PATH" in captured["env"]


def test_nonzero_exit_becomes_provider_error(provider, monkeypatch):
    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "not logged in"

        return Result()

    monkeypatch.setattr("jobhunter.llm.claude_cli.subprocess.run", fake_run)

    with pytest.raises(LLMProviderError, match="not logged in"):
        provider.structure_resume("text")


# --- T030 [P] [US4] --------------------------------------------------------
# Written first per Constitution VII (Test-First Development): pins down the
# `ClaudeCLIProvider.rerank(candidates, profile)` contract from research.md
# §3 before T032 (LLMProvider.rerank ABC method) and T033 (this
# implementation) exist. Expected to fail with AttributeError — 'ClaudeCLIProvider'
# object has no attribute 'rerank' — until those tasks land.


@pytest.fixture
def rerank_candidates() -> list[dict]:
    """Redacted candidate dicts as scoring/rerank.py would pass them in —
    only id/title/description/matched_skills, never prefs.yaml or tracking
    state (research.md §3, Constitution I)."""
    return [
        {
            "id": "job-1",
            "title": "Senior Backend Engineer",
            "description": "Own Python/Django services at scale.",
            "matched_skills": ["Python", "Django"],
        },
        {
            "id": "job-2",
            "title": "Staff Software Engineer, Platform",
            "description": "Backend scope work across distributed systems.",
            "matched_skills": ["Distributed Systems", "Kafka"],
        },
    ]


@pytest.fixture
def rerank_response() -> dict:
    """A `claude -p ... --output-format json` wrapper whose `result` is a
    JSON object mapping job id -> reason string (not a Profile)."""
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": json.dumps(
            {
                "job-1": "Great match on Python/Django experience.",
                "job-2": "Strong scope overlap with backend roles.",
            }
        ),
        "session_id": "00000000-0000-4000-8000-000000000000",
        "total_cost_usd": 0,
    }


def test_rerank_builds_bounded_prompt_and_parses_reasons(
    provider, profile_payload, rerank_candidates, rerank_response, monkeypatch
):
    """The prompt sent to `claude -p` must carry the candidates' titles and
    the profile's skills, and the parsed result must map job id -> reason."""
    from jobhunter.models.profile import Profile

    profile = Profile.model_validate(profile_payload)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")

        class Result:
            returncode = 0
            stdout = json.dumps(rerank_response)
            stderr = ""

        return Result()

    monkeypatch.setattr("jobhunter.llm.claude_cli.subprocess.run", fake_run)

    reasons = provider.rerank(rerank_candidates, profile)

    prompt = " ".join(str(part) for part in captured["cmd"])
    for candidate in rerank_candidates:
        assert candidate["title"] in prompt
    for skill in profile.skills:
        assert skill in prompt

    assert reasons == {
        "job-1": "Great match on Python/Django experience.",
        "job-2": "Strong scope overlap with backend roles.",
    }


def test_rerank_malformed_result_becomes_provider_error(
    provider, profile_payload, rerank_candidates, monkeypatch
):
    """A `result` that isn't valid JSON (or isn't a dict[str, str]) must raise
    LLMProviderError — mirrors test_nonzero_exit_becomes_provider_error, but
    for a parse failure instead of a nonzero exit."""
    from jobhunter.models.profile import Profile

    profile = Profile.model_validate(profile_payload)

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = json.dumps({"type": "result", "result": "not valid json"})
            stderr = ""

        return Result()

    monkeypatch.setattr("jobhunter.llm.claude_cli.subprocess.run", fake_run)

    with pytest.raises(LLMProviderError):
        provider.rerank(rerank_candidates, profile)


def test_rerank_non_dict_result_becomes_provider_error(
    provider, profile_payload, rerank_candidates, monkeypatch
):
    """A `result` that parses to a JSON array (or non-string values) instead
    of a dict[str, str] must also raise LLMProviderError."""
    from jobhunter.models.profile import Profile

    profile = Profile.model_validate(profile_payload)

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = json.dumps({"type": "result", "result": json.dumps(["job-1", "job-2"])})
            stderr = ""

        return Result()

    monkeypatch.setattr("jobhunter.llm.claude_cli.subprocess.run", fake_run)

    with pytest.raises(LLMProviderError):
        provider.rerank(rerank_candidates, profile)
