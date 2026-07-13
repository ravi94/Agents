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
