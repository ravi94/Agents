"""T017 [US2] — unit tests for Preferences validation (models/preferences.py).

The executable form of ``contracts/prefs.schema.md``: a well-formed prefs file
parses; each malformed field errors *naming that field* (SC-006) so the user can
fix it without reading logs; and a soft-weight sum that drifts from 1.0 is a
**warning only** — the user's chosen values are preserved, never silently
rewritten (FR-008). Written first (Constitution VII) — expected to fail until
T019.
"""

from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError

from jobhunter.models.preferences import Preferences, load_preferences


def valid_prefs_dict() -> dict:
    """A canonical, fully valid preferences payload (weights sum to exactly 1.0)."""
    return {
        "hard_filters": {
            "locations": ["Bangalore", "Remote"],
            "work_modes": ["remote", "hybrid", "onsite"],
            "company_types_allow": ["product", "gcc"],
            "company_types_deny": ["services", "consultancy", "staffing"],
            "comp_floor_lpa": 60,
            "seniority_floor": "senior",
        },
        "soft_weights": {
            "work_life_balance": 0.40,
            "stability": 0.30,
            "scope": 0.20,
            "comp": 0.10,
        },
        "alerting": {
            "score_threshold": 0.70,
            "max_alerts_per_run": 10,
        },
    }


def test_valid_preferences_parse_without_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        prefs = Preferences.model_validate(valid_prefs_dict())

    assert prefs.hard_filters.locations == ["Bangalore", "Remote"]
    assert prefs.hard_filters.seniority_floor == "senior"
    assert prefs.soft_weights.work_life_balance == 0.40
    assert prefs.alerting.max_alerts_per_run == 10
    # A sum of exactly 1.0 is on-target: no weight-sum warning.
    assert not [w for w in caught if "weight" in str(w.message).lower()]


def test_valid_yaml_file_loads(tmp_path):
    import yaml

    path = tmp_path / "prefs.yaml"
    path.write_text(yaml.safe_dump(valid_prefs_dict()))

    prefs = load_preferences(path)

    assert isinstance(prefs, Preferences)
    assert prefs.hard_filters.comp_floor_lpa == 60


def test_unrecognized_work_mode_errors_naming_field():
    payload = valid_prefs_dict()
    payload["hard_filters"]["work_modes"] = ["remote", "telepathic"]

    with pytest.raises(ValidationError) as exc:
        Preferences.model_validate(payload)

    message = str(exc.value)
    assert "work_modes" in message
    assert "telepathic" in message  # FR-013: names the offending value


def test_negative_comp_floor_errors():
    payload = valid_prefs_dict()
    payload["hard_filters"]["comp_floor_lpa"] = -5

    with pytest.raises(ValidationError) as exc:
        Preferences.model_validate(payload)

    assert "comp_floor_lpa" in str(exc.value)


def test_out_of_enum_seniority_floor_errors_naming_field():
    payload = valid_prefs_dict()
    payload["hard_filters"]["seniority_floor"] = "overlord"

    with pytest.raises(ValidationError) as exc:
        Preferences.model_validate(payload)

    message = str(exc.value)
    assert "seniority_floor" in message
    assert "overlord" in message


def test_allow_deny_overlap_errors():
    payload = valid_prefs_dict()
    payload["hard_filters"]["company_types_allow"] = ["product", "services"]
    payload["hard_filters"]["company_types_deny"] = ["services", "staffing"]

    with pytest.raises(ValidationError) as exc:
        Preferences.model_validate(payload)

    message = str(exc.value)
    # Contradictory config: the overlapping value is named so the user can fix it.
    assert "services" in message
    assert "company_types_allow" in message or "company_types_deny" in message


def test_empty_locations_errors():
    payload = valid_prefs_dict()
    payload["hard_filters"]["locations"] = []

    with pytest.raises(ValidationError) as exc:
        Preferences.model_validate(payload)

    assert "locations" in str(exc.value)


def test_soft_weight_out_of_range_errors():
    payload = valid_prefs_dict()
    payload["soft_weights"]["comp"] = 1.5

    with pytest.raises(ValidationError) as exc:
        Preferences.model_validate(payload)

    assert "comp" in str(exc.value)


def test_score_threshold_out_of_range_errors():
    payload = valid_prefs_dict()
    payload["alerting"]["score_threshold"] = 1.7

    with pytest.raises(ValidationError) as exc:
        Preferences.model_validate(payload)

    assert "score_threshold" in str(exc.value)


def test_negative_max_alerts_errors():
    payload = valid_prefs_dict()
    payload["alerting"]["max_alerts_per_run"] = -1

    with pytest.raises(ValidationError) as exc:
        Preferences.model_validate(payload)

    assert "max_alerts_per_run" in str(exc.value)


def test_non_integer_max_alerts_errors():
    payload = valid_prefs_dict()
    payload["alerting"]["max_alerts_per_run"] = 2.5

    with pytest.raises(ValidationError) as exc:
        Preferences.model_validate(payload)

    assert "max_alerts_per_run" in str(exc.value)


def test_weight_sum_drift_warns_but_preserves_values():
    payload = valid_prefs_dict()
    # Sum = 0.90 — off-target beyond tolerance, but a legitimate user choice.
    payload["soft_weights"] = {
        "work_life_balance": 0.40,
        "stability": 0.30,
        "scope": 0.10,
        "comp": 0.10,
    }

    with pytest.warns(UserWarning, match="weight"):
        prefs = Preferences.model_validate(payload)

    # FR-008: values are preserved exactly, never renormalized behind the user's back.
    assert prefs.soft_weights.work_life_balance == 0.40
    assert prefs.soft_weights.stability == 0.30
    assert prefs.soft_weights.scope == 0.10
    assert prefs.soft_weights.comp == 0.10
