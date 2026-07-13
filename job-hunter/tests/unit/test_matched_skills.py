"""T010 [P] [US1] — unit tests for `matched_skills` selection in the composite scorer.

Per contracts/scoring_algorithm.md `matched_skills`: populated alongside
`scope`, every profile skill whose *individual* embedding scores above a
fixed similarity threshold against the job text, ordered by similarity
descending; empty list (not null) when nothing clears the threshold; falls
back to keyword-overlap when `embeddings.ollama.embed` returns `None`.
Written first (Constitution VII) — expected to fail until T013 implements
`jobhunter.scoring.scorer.score_job`.

Assumptions made about the (not-yet-pinned) `embed` call shape, since T013's
implementer should satisfy these exactly:
  - The job-side text passed to `embed()` for both `scope` and
    `matched_skills` is built from `job["title"]` and `job["description"]`
    and therefore contains both verbatim somewhere in the string (order/
    separator unspecified). Tests key on a unique marker substring placed in
    `description` rather than an exact string match, so they don't depend on
    the exact concatenation format.
  - Each profile skill's individual embedding is computed by calling
    `embed(skill)` with the bare skill string as `text` (this is the
    simplest reading of "each profile skill's individual similarity").
    The mock keys on an *exact* (stripped) match against each skill name.
  - Any other text `embed()` is called with (e.g. the combined
    `profile.skills + profile.roles` text used for `scope`'s other side) is
    not asserted on here — the mock returns a fixed neutral default vector
    for it so `score_job` can run to completion without raising.
  - Vectors are 2-D for readability; only their cosine similarity matters.
    "Clearly above threshold" is modeled as identical/near-identical vectors
    (cosine ~0.94-1.0); "clearly below threshold" is modeled as opposite
    vectors (cosine -1.0), so the assertions hold for any reasonable fixed
    threshold the implementation picks (whether applied to the raw [-1, 1]
    cosine or the [0, 1]-rescaled form used for `scope`).
"""

from __future__ import annotations

import yaml
import pytest

from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile

# Import deferred until inside the tests would also work, but importing at
# module level is the more standard pytest style here (see
# test_embeddings_ollama.py) and makes the expected ModuleNotFoundError
# surface immediately at collection time.
from jobhunter.scoring.scorer import score_job

# Unique token embedded in job descriptions so the mock can recognize "this
# is the job-side text" regardless of exactly how title/description are
# joined before being passed to `embed()`.
_JOB_MARKER = "JOBTEXT-T010-MARKER"

_DEFAULT_VECTOR = [0.1, 0.1]


def _load_prefs(fixtures_dir) -> Preferences:
    data = yaml.safe_load((fixtures_dir / "scoring_prefs.yaml").read_text())
    return Preferences.model_validate(data)


def _make_profile(skills: list[str]) -> Profile:
    return Profile(
        skills=skills,
        source_resume_filename="resume.pdf",
        parsed_at="2026-01-01T00:00:00+00:00",
    )


def _make_job(description: str, *, title: str = "Backend Engineer") -> dict:
    return {
        "title": title,
        "description": f"{_JOB_MARKER} {description}",
        "company": "Acme Corp",
        "salary": "40 LPA",
    }


def _make_fake_embed(job_vector, skill_vectors: dict[str, list[float]]):
    """Build a fake `embed(text, **kwargs)` keyed off the text content.

    - exact (stripped) match against a known skill name -> that skill's vector
    - text containing the job marker -> the job vector
    - anything else -> a fixed neutral default vector
    """

    def fake_embed(text: str, **kwargs) -> list[float] | None:
        stripped = text.strip()
        if stripped in skill_vectors:
            return skill_vectors[stripped]
        if _JOB_MARKER in text:
            return job_vector
        return _DEFAULT_VECTOR

    return fake_embed


def _make_none_embed():
    def fake_embed(text: str, **kwargs) -> list[float] | None:
        return None

    return fake_embed


def test_matched_skills_ordered_by_similarity_descending(monkeypatch, fixtures_dir):
    profile = _make_profile(["Python", "Excel", "Kubernetes"])
    prefs = _load_prefs(fixtures_dir)
    job = _make_job("Series A startup building a payments platform.")

    job_vector = [1.0, 0.0]
    skill_vectors = {
        "Python": [1.0, 0.0],  # identical to job vector -> cosine 1.0
        "Kubernetes": [0.94, 0.34],  # near-identical -> cosine ~0.94
        "Excel": [-1.0, 0.0],  # opposite -> cosine -1.0, clearly excluded
    }
    monkeypatch.setattr(
        "jobhunter.embeddings.ollama.embed",
        _make_fake_embed(job_vector, skill_vectors),
    )

    result = score_job(job, profile, prefs)

    assert result.matched_skills == ["Python", "Kubernetes"]


def test_matched_skills_empty_list_when_nothing_clears_threshold(monkeypatch, fixtures_dir):
    profile = _make_profile(["Python", "Excel", "Kubernetes"])
    prefs = _load_prefs(fixtures_dir)
    job = _make_job("Series A startup building a payments platform.")

    job_vector = [1.0, 0.0]
    skill_vectors = {
        # All skills point opposite the job vector -> cosine -1.0 for every one.
        "Python": [-1.0, 0.0],
        "Kubernetes": [-1.0, 0.0],
        "Excel": [-1.0, 0.0],
    }
    monkeypatch.setattr(
        "jobhunter.embeddings.ollama.embed",
        _make_fake_embed(job_vector, skill_vectors),
    )

    result = score_job(job, profile, prefs)

    assert result.matched_skills == []
    assert result.matched_skills is not None


def test_matched_skills_keyword_overlap_fallback_when_embed_unavailable(monkeypatch, fixtures_dir):
    profile = _make_profile(["Python", "AWS", "Excel"])
    prefs = _load_prefs(fixtures_dir)
    # "Python" and "AWS" literally appear in the job text; "Excel" never does.
    job = _make_job(
        "We use Python extensively and deploy everything on AWS. "
        "No spreadsheet tools are involved in this role.",
        title="Backend Engineer",
    )
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _make_none_embed())

    result = score_job(job, profile, prefs)

    assert "Python" in result.matched_skills
    assert "AWS" in result.matched_skills
    assert "Excel" not in result.matched_skills


def test_score_job_does_not_raise_with_embeddings_available(monkeypatch, fixtures_dir):
    profile = _make_profile(["Python", "Excel", "Kubernetes"])
    prefs = _load_prefs(fixtures_dir)
    job = _make_job("Series A startup building a payments platform.")

    job_vector = [1.0, 0.0]
    skill_vectors = {
        "Python": [1.0, 0.0],
        "Kubernetes": [0.94, 0.34],
        "Excel": [-1.0, 0.0],
    }
    monkeypatch.setattr(
        "jobhunter.embeddings.ollama.embed",
        _make_fake_embed(job_vector, skill_vectors),
    )

    result = score_job(job, profile, prefs)

    assert isinstance(result.matched_skills, list)


def test_score_job_does_not_raise_when_embeddings_unavailable(monkeypatch, fixtures_dir):
    profile = _make_profile(["Python", "AWS", "Excel"])
    prefs = _load_prefs(fixtures_dir)
    job = _make_job("We use Python extensively and deploy everything on AWS.")
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _make_none_embed())

    result = score_job(job, profile, prefs)

    assert isinstance(result.matched_skills, list)
