"""Shared pytest fixtures for the jobhunter test suite."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONTRACTS_DIR = Path(__file__).parent.parent / "specs" / "001-resume-profile-prefs" / "contracts"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_resume_pdf() -> Path:
    return FIXTURES_DIR / "sample_resume.pdf"


@pytest.fixture
def scanned_image_pdf() -> Path:
    return FIXTURES_DIR / "scanned_image.pdf"


@pytest.fixture
def profile_schema() -> dict:
    """The Profile JSON Schema contract (source of truth for T009)."""
    return json.loads((CONTRACTS_DIR / "profile.schema.json").read_text())


@pytest.fixture
def claude_response() -> dict:
    """The full `claude -p ... --output-format json` wrapper fixture."""
    return json.loads((FIXTURES_DIR / "claude_profile_response.json").read_text())


@pytest.fixture
def profile_payload(claude_response) -> dict:
    """The inner structured-profile object the provider parses out of `result`."""
    return json.loads(claude_response["result"])
