"""T009 [US1] — unit tests for the Profile pydantic model (models/profile.py).

Validates the model against the Profile JSON Schema contract: a representative
structuring response parses cleanly; an all-empty `skills` extraction is a parse
failure (FR-012), not a valid profile; unstated fields default to null and are
never fabricated (Constitution V). Written first (Constitution VII) — expected
to fail until T012.
"""

import jsonschema
import pytest
from pydantic import ValidationError

from jobhunter.models.profile import Experience, Profile


def test_parses_representative_response(profile_payload):
    profile = Profile.model_validate(profile_payload)

    assert profile.full_name == "Ravi Bhushan"
    assert "Java" in profile.skills
    assert profile.seniority == "senior"
    assert profile.roles == ["Backend Engineer", "Software Engineer"]
    assert profile.source_resume_filename == "sample_resume.pdf"
    assert len(profile.experience) == 2
    assert isinstance(profile.experience[0], Experience)
    assert profile.experience[0].company == "Acme SaaS"
    # A current role has a null end date — surfaced as unknown, not guessed.
    assert profile.experience[0].end is None


def test_rejects_empty_skills(profile_payload):
    profile_payload["skills"] = []
    with pytest.raises(ValidationError):
        Profile.model_validate(profile_payload)


def test_nullable_fields_default_to_null_not_fabricated():
    # A minimal profile with no seniority basis must surface null, never a guess.
    profile = Profile(
        skills=["Python"],
        experience=[],
        roles=[],
        source_resume_filename="r.pdf",
        parsed_at="2026-07-13T00:00:00Z",
    )

    assert profile.full_name is None
    assert profile.seniority is None
    assert profile.total_years_experience is None


def test_rejects_out_of_enum_seniority(profile_payload):
    profile_payload["seniority"] = "wizard"
    with pytest.raises(ValidationError):
        Profile.model_validate(profile_payload)


def test_serialized_profile_conforms_to_schema(profile_payload, profile_schema):
    profile = Profile.model_validate(profile_payload)

    dumped = profile.model_dump(mode="json")

    # additionalProperties:false in the contract — the model must emit exactly
    # the contracted field names and JSON-native types (e.g. parsed_at string).
    jsonschema.validate(instance=dumped, schema=profile_schema)


def test_experience_requires_company_and_title():
    with pytest.raises(ValidationError):
        Experience(title="Engineer")  # missing company
