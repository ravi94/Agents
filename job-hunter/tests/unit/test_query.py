"""T009 [US1] — unit tests for discovery query derivation (discovery/query.py).

Covers the default derivation (`profile.roles` × `prefs.hard_filters.locations`),
the `prefs.search.keywords` override replacing the profile-derived keyword set,
and the clean no-op when neither side yields a keyword term (data-model.md
"SearchQuery"). Written first (Constitution VII) — expected to fail until T014
(optional `search` prefs field) and T015 (`derive_queries`) land.
"""

from __future__ import annotations

from jobhunter.discovery.query import derive_queries
from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.sources.base import SearchQuery


def _profile(**overrides) -> Profile:
    base = {
        "skills": ["Python", "Distributed Systems"],
        "roles": ["Staff Backend Engineer", "Senior Platform Engineer"],
        "seniority": "senior",
        "source_resume_filename": "resume.pdf",
        "parsed_at": "2026-07-01T00:00:00+00:00",
    }
    base.update(overrides)
    return Profile.model_validate(base)


def _prefs(**overrides) -> Preferences:
    base = {
        "hard_filters": {
            "locations": ["Bangalore", "Remote"],
            "work_modes": ["remote", "hybrid", "onsite"],
            "comp_floor_lpa": 40,
            "seniority_floor": "senior",
        },
        "soft_weights": {
            "work_life_balance": 0.25,
            "stability": 0.25,
            "scope": 0.25,
            "comp": 0.25,
        },
        "alerting": {"score_threshold": 0.7, "max_alerts_per_run": 5},
    }
    base.update(overrides)
    return Preferences.model_validate(base)


def test_roles_cross_locations_builds_queries():
    queries = derive_queries(_profile(), _prefs())

    assert set(queries) == {
        SearchQuery(keywords="Staff Backend Engineer", location="Bangalore"),
        SearchQuery(keywords="Staff Backend Engineer", location="Remote"),
        SearchQuery(keywords="Senior Platform Engineer", location="Bangalore"),
        SearchQuery(keywords="Senior Platform Engineer", location="Remote"),
    }


def test_search_keywords_override_replaces_profile_roles():
    prefs = _prefs(search={"keywords": ["Data Platform Lead"]})

    queries = derive_queries(_profile(), prefs)

    assert set(queries) == {
        SearchQuery(keywords="Data Platform Lead", location="Bangalore"),
        SearchQuery(keywords="Data Platform Lead", location="Remote"),
    }
    # The profile-derived roles are fully replaced, not merged in.
    assert all("Engineer" not in q.keywords for q in queries)


def test_empty_search_keywords_falls_back_to_profile_roles():
    prefs = _prefs(search={"keywords": []})

    queries = derive_queries(_profile(), prefs)

    assert {q.keywords for q in queries} == {
        "Staff Backend Engineer",
        "Senior Platform Engineer",
    }


def test_empty_profile_and_prefs_yields_no_queries():
    profile = _profile(roles=[], seniority=None)

    queries = derive_queries(profile, _prefs())

    assert queries == []
