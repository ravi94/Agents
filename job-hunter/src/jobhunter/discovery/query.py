"""T015 [US1] — discovery query derivation from profile and preferences.

Builds the ``SearchQuery`` set each source fetches against: the candidate's
role terms crossed with their required locations (data-model.md
"SearchQuery"). ``prefs.search.keywords`` — when present and non-empty —
replaces the profile-derived roles outright rather than merging with them.
"""

from __future__ import annotations

from jobhunter.models.preferences import Preferences
from jobhunter.models.profile import Profile
from jobhunter.sources.base import SearchQuery


def derive_queries(profile: Profile, prefs: Preferences) -> list[SearchQuery]:
    """Cross keyword terms with ``prefs.hard_filters.locations`` into queries."""
    if prefs.search and prefs.search.keywords:
        keyword_terms = prefs.search.keywords
    else:
        keyword_terms = profile.roles

    if not keyword_terms:
        return []

    return [
        SearchQuery(keywords=keyword, location=location)
        for keyword in keyword_terms
        for location in prefs.hard_filters.locations
    ]
