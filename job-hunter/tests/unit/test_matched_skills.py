"""T010 [P] [US1] — unit tests for `matched_skills` selection in the composite scorer.

Per contracts/scoring_algorithm.md `matched_skills`: every profile skill that
*literally appears* in the job text (`title + description`, case-insensitive,
word-boundary aware), in profile order; empty list (not null) when nothing
appears. This is deliberately literal, not semantic — it is the per-skill
evidence beneath `scope`, so a skill must NOT be reported merely because its
embedding is close to the job's overall topic (a Go role must not "match"
Java). Unlike `scope`, `matched_skills` does not depend on the embedding
endpoint at all.

`score_job` still calls `embeddings.ollama.embed` for the `scope` component, so
these tests patch it with a fixed neutral fake purely so `score_job` runs to
completion — the matched-skills assertions never depend on what it returns.
"""

from __future__ import annotations

import yaml

from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.scoring.scorer import score_job

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
        "description": description,
        "company": "Acme Corp",
        "salary": "40 LPA",
    }


def _fixed_embed(text: str, **kwargs) -> list[float]:
    """Neutral stand-in for `scope`'s embedding — matched_skills ignores it."""
    return _DEFAULT_VECTOR


def test_matched_skills_are_the_literal_hits_in_profile_order(monkeypatch, fixtures_dir):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _fixed_embed)
    profile = _make_profile(["Python", "AWS", "Excel"])
    prefs = _load_prefs(fixtures_dir)
    # "Python" and "AWS" appear in the text; "Excel" never does.
    job = _make_job(
        "We use Python extensively and deploy everything on AWS. "
        "No spreadsheet tools are involved in this role."
    )

    result = score_job(job, profile, prefs)

    # Literal hits, kept in profile order (not similarity order).
    assert result.matched_skills == ["Python", "AWS"]


def test_matched_skills_excludes_semantically_related_but_absent_skill(monkeypatch, fixtures_dir):
    """A Go role must not "match" Java just because both are backend software."""
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _fixed_embed)
    profile = _make_profile(["Go", "PostgreSQL", "Java"])
    prefs = _load_prefs(fixtures_dir)
    job = _make_job(
        "Backend Developer (Go). Solid Go fundamentals, REST APIs, and "
        "PostgreSQL schema design. No JVM stack here.",
        title="Backend Developer (Go)",
    )

    result = score_job(job, profile, prefs)

    assert "Go" in result.matched_skills
    assert "PostgreSQL" in result.matched_skills
    # "Java" is nowhere in the posting — must not appear despite being backend-ish.
    assert "Java" not in result.matched_skills


def test_matched_skills_word_boundary_avoids_substring_false_positives(monkeypatch, fixtures_dir):
    """"Go" must match the token "Go" but not "Google"."""
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _fixed_embed)
    prefs = _load_prefs(fixtures_dir)

    # "Go" appears only inside "Google" — must NOT match.
    profile = _make_profile(["Go"])
    job = _make_job("We are a Google Cloud shop building data pipelines.")
    assert score_job(job, profile, prefs).matched_skills == []

    # "Go" as a standalone token — must match.
    job2 = _make_job("Strong Go and gRPC experience required.")
    assert score_job(job2, profile, prefs).matched_skills == ["Go"]


def test_matched_skills_matches_punctuated_and_multiword_skills(monkeypatch, fixtures_dir):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _fixed_embed)
    profile = _make_profile(["C++", "Node.js", "Distributed Systems"])
    prefs = _load_prefs(fixtures_dir)
    job = _make_job(
        "Work across C++ services and Node.js gateways on our "
        "distributed systems platform."
    )

    result = score_job(job, profile, prefs)

    assert result.matched_skills == ["C++", "Node.js", "Distributed Systems"]


def test_matched_skills_is_case_insensitive(monkeypatch, fixtures_dir):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _fixed_embed)
    profile = _make_profile(["Kubernetes", "Kafka"])
    prefs = _load_prefs(fixtures_dir)
    job = _make_job("Deploys run on KUBERNETES; events flow through kafka.")

    result = score_job(job, profile, prefs)

    assert result.matched_skills == ["Kubernetes", "Kafka"]


def test_matched_skills_empty_list_when_nothing_appears(monkeypatch, fixtures_dir):
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", _fixed_embed)
    profile = _make_profile(["Python", "Excel", "Kubernetes"])
    prefs = _load_prefs(fixtures_dir)
    job = _make_job("A fully non-technical customer success role.")

    result = score_job(job, profile, prefs)

    assert result.matched_skills == []
    assert result.matched_skills is not None


def test_matched_skills_independent_of_embedding_availability(monkeypatch, fixtures_dir):
    """Even when `embed` returns None (scope falls back), literal matching still works."""
    monkeypatch.setattr("jobhunter.embeddings.ollama.embed", lambda text, **kw: None)
    profile = _make_profile(["Python", "AWS", "Excel"])
    prefs = _load_prefs(fixtures_dir)
    job = _make_job("We use Python and deploy on AWS; no spreadsheets here.")

    result = score_job(job, profile, prefs)

    assert result.matched_skills == ["Python", "AWS"]
