"""T010 [US1] — integration test for the resume parser (resume/parser.py).

Exercises the full extract → structure → validate → atomic-write flow with a
mock `LLMProvider` (no live `claude`): a resume becomes a persisted Profile; a
provider failure/malformed response leaves any prior `profile.json` untouched
(FR-012, atomic write); and only the extracted resume text — never the path or
filename — reaches the provider (FR-014, Constitution I). Written first
(Constitution VII) — expected to fail until T015.
"""

import json

import pytest

from jobhunter import config
from jobhunter.llm.provider import LLMProvider, LLMProviderError
from jobhunter.models.profile import Profile
from jobhunter.resume.extract import extract_text
from jobhunter.resume.parser import parse_resume


class RecordingProvider(LLMProvider):
    """Returns a fixed Profile and records exactly what it was handed."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.received_text: str | None = None
        self.call_count = 0

    def structure_resume(self, resume_text: str) -> Profile:
        self.received_text = resume_text
        self.call_count += 1
        return Profile.model_validate(self._payload)

    def rerank(self, candidates: list[dict], profile: Profile) -> dict[str, str]:
        raise NotImplementedError("not exercised by this test module")


class FailingProvider(LLMProvider):
    """Simulates a provider error / malformed response (raises, never returns)."""

    def __init__(self):
        self.call_count = 0

    def structure_resume(self, resume_text: str) -> Profile:
        self.call_count += 1
        raise LLMProviderError("malformed JSON from provider")

    def rerank(self, candidates: list[dict], profile: Profile) -> dict[str, str]:
        raise NotImplementedError("not exercised by this test module")


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))


def test_resume_becomes_persisted_profile(sample_resume_pdf, profile_payload):
    provider = RecordingProvider(profile_payload)

    profile = parse_resume(sample_resume_pdf, provider)

    assert isinstance(profile, Profile)
    assert profile.skills, "expected a non-empty skill list"

    # Persisted atomically to the resolved profile.json path...
    written = config.profile_path()
    assert written.exists()
    # ...and it round-trips back into a valid Profile.
    reloaded = Profile.model_validate(json.loads(written.read_text()))
    assert reloaded.skills == profile.skills


def test_only_resume_text_is_sent_to_provider(sample_resume_pdf, profile_payload):
    provider = RecordingProvider(profile_payload)

    parse_resume(sample_resume_pdf, provider)

    assert provider.call_count == 1
    # Exactly the extracted text — not the path, not the filename (FR-014).
    assert provider.received_text == extract_text(sample_resume_pdf)
    assert str(sample_resume_pdf) not in provider.received_text
    assert sample_resume_pdf.name not in provider.received_text


def test_provider_failure_leaves_existing_profile_intact(sample_resume_pdf):
    written = config.profile_path()
    written.parent.mkdir(parents=True, exist_ok=True)
    sentinel = '{"existing": "profile", "skills": ["Rust"]}'
    written.write_text(sentinel)

    with pytest.raises(LLMProviderError):
        parse_resume(sample_resume_pdf, FailingProvider())

    # Atomic guarantee: the prior file is byte-for-byte unchanged (FR-012).
    assert written.read_text() == sentinel


def test_no_profile_written_on_failure_when_none_existed(sample_resume_pdf):
    written = config.profile_path()

    with pytest.raises(LLMProviderError):
        parse_resume(sample_resume_pdf, FailingProvider())

    assert not written.exists()
