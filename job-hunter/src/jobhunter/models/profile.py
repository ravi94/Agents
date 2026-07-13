"""T012 [US1] — the structured candidate Profile and its atomic persistence.

Derived once from a resume PDF and reused on later runs (FR-004). The model is
the executable form of ``contracts/profile.schema.json``: skills must be
non-empty (an all-empty extraction is a parse failure, not a valid profile,
FR-012), and unstated fields default to null — never fabricated (Constitution
V). Persistence is atomic: a write either fully replaces ``profile.json`` or
leaves the prior file byte-for-byte intact.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobhunter import config

Seniority = Literal["junior", "mid", "senior", "staff", "principal"]


class Experience(BaseModel):
    """One role in the candidate's history. Company and title are required."""

    model_config = ConfigDict(extra="forbid")

    company: str
    title: str
    start: str | None = None
    end: str | None = None
    summary: str | None = None


class Profile(BaseModel):
    """A validated candidate profile derived from a resume (M1)."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    skills: list[str] = Field(min_length=1)
    experience: list[Experience] = Field(default_factory=list)
    seniority: Seniority | None = None
    roles: list[str] = Field(default_factory=list)
    total_years_experience: float | None = Field(default=None, ge=0)
    source_resume_filename: str
    # ISO-8601 date-time string (kept as str so it round-trips through JSON
    # unchanged and conforms directly to the contract's date-time field).
    parsed_at: str


def save_profile(profile: Profile, path: Path | None = None) -> Path:
    """Atomically persist ``profile`` to ``profile.json`` (default location).

    Writes to a sibling temp file and ``os.replace``s it into place, so a
    failure mid-write can never leave a partial or clobbered profile.
    """
    target = path or config.profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = profile.model_dump(mode="json")
    tmp = target.with_name(f"{target.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, target)
    return target


def load_profile(path: Path | None = None) -> Profile:
    """Load and validate the persisted profile from ``profile.json``."""
    source = path or config.profile_path()
    return Profile.model_validate(json.loads(source.read_text()))
