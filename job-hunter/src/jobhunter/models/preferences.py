"""T019 [US2] — the Preferences model and its YAML load/validate.

The executable form of ``contracts/prefs.schema.md``: user-owned matching
configuration, seeded once by the guided interview and hand-editable thereafter
(FR-007). Validation runs on *every* load; each malformed field errors naming
that field (SC-006) so it can be fixed without reading logs. A soft-weight sum
that drifts from 1.0 is a **warning only** — the user's chosen values are
preserved, never silently renormalized (FR-008).
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from jobhunter import config
from jobhunter.models.profile import Seniority

WorkMode = Literal["remote", "hybrid", "onsite"]

# Guidance tolerance for the soft-weight sum (data-model.md): drift beyond this
# warns but never blocks or rewrites the values.
WEIGHT_SUM_TARGET = 1.0
WEIGHT_SUM_TOLERANCE = 0.05


class HardFilters(BaseModel):
    """Non-negotiable gates: a job failing any of these is filtered out."""

    model_config = ConfigDict(extra="forbid")

    locations: list[str] = Field(min_length=1)
    work_modes: list[WorkMode] = Field(min_length=1)
    company_types_allow: list[str] = Field(default_factory=list)
    company_types_deny: list[str] = Field(default_factory=list)
    comp_floor_lpa: float = Field(ge=0)
    seniority_floor: Seniority

    @model_validator(mode="after")
    def _allow_deny_disjoint(self) -> HardFilters:
        overlap = set(self.company_types_allow) & set(self.company_types_deny)
        if overlap:
            named = ", ".join(sorted(overlap))
            raise ValueError(
                f"company_types_allow and company_types_deny both contain: {named} "
                "(a company type cannot be both allowed and denied)"
            )
        return self


class SoftWeights(BaseModel):
    """Desirability tuning; each weight in [0, 1], sum guided toward ~1.0."""

    model_config = ConfigDict(extra="forbid")

    work_life_balance: float = Field(ge=0, le=1)
    stability: float = Field(ge=0, le=1)
    scope: float = Field(ge=0, le=1)
    comp: float = Field(ge=0, le=1)

    def sum(self) -> float:
        return self.work_life_balance + self.stability + self.scope + self.comp


class Alerting(BaseModel):
    """Notification thresholds — defined now, consumed at the notifier milestone."""

    model_config = ConfigDict(extra="forbid")

    score_threshold: float = Field(ge=0, le=1)
    max_alerts_per_run: int = Field(ge=0)


class Preferences(BaseModel):
    """Validated matching configuration loaded from ``prefs.yaml`` (M1)."""

    model_config = ConfigDict(extra="forbid")

    hard_filters: HardFilters
    soft_weights: SoftWeights
    alerting: Alerting

    @model_validator(mode="after")
    def _warn_on_weight_drift(self) -> Preferences:
        total = self.soft_weights.sum()
        if abs(total - WEIGHT_SUM_TARGET) > WEIGHT_SUM_TOLERANCE:
            warnings.warn(
                f"soft_weights sum to {total:.2f}, not ~{WEIGHT_SUM_TARGET:.1f} "
                "— values are kept as-is; adjust them if this was unintended",
                UserWarning,
                stacklevel=2,
            )
        return self


def load_preferences(path: Path | None = None) -> Preferences:
    """Load and validate preferences from ``prefs.yaml`` (default location).

    Raises :class:`pydantic.ValidationError` (field-named) on any invalid value;
    emits a :class:`UserWarning` — never an error — when the soft-weight sum
    drifts from 1.0.
    """
    source = path or config.prefs_path()
    data = yaml.safe_load(source.read_text())
    return Preferences.model_validate(data)


def save_preferences(prefs: Preferences, path: Path | None = None) -> Path:
    """Serialize ``prefs`` to ``prefs.yaml`` (default location) as readable YAML."""
    target = path or config.prefs_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = prefs.model_dump(mode="json")
    target.write_text(yaml.safe_dump(payload, sort_keys=False))
    return target
