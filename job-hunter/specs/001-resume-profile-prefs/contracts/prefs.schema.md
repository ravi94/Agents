# Preferences Contract (`prefs.yaml`)

Human-editable YAML validated on every load. Full field rules in [../data-model.md](../data-model.md#entity-preferences-prefsyaml). This file is the authoritative shape M3's scorer will consume.

## Canonical example

```yaml
hard_filters:
  locations: [Bangalore, Remote]         # non-empty list of strings
  work_modes: [remote, hybrid, onsite]   # subset of {remote, hybrid, onsite}
  company_types_allow: [product, gcc]    # strings
  company_types_deny:  [services, consultancy, staffing]
  comp_floor_lpa: 60                      # number >= 0
  seniority_floor: senior                 # junior|mid|senior|staff|principal

soft_weights:                             # each in [0,1]; sum ~1.0 (guidance, warn only)
  work_life_balance: 0.40
  stability:         0.30
  scope:             0.20
  comp:              0.10

alerting:                                 # defined now; consumed at M4 (notifier)
  score_threshold: 0.70                   # number in [0,1]
  max_alerts_per_run: 10                  # integer >= 0
```

## Validation summary (errors vs warnings)

| Condition | Result |
|---|---|
| Unrecognized `work_modes` value | **error**, names the value (FR-013) |
| `comp_floor_lpa` negative | **error** |
| `seniority_floor` not in enum | **error** |
| `soft_weights` entry outside [0,1] | **error** |
| `company_types_allow` ∩ `company_types_deny` non-empty | **error** (contradictory) |
| `score_threshold` outside [0,1] | **error** |
| `max_alerts_per_run` negative or non-integer | **error** |
| `soft_weights` sum ≠ 1.0 (±tolerance) | **warning only** — value preserved, not silently altered (FR-008) |
| Empty `locations` | **error** (would filter out everything) |

## Guarantees

- Hand-edits are honored on next load without re-running the guided interview (FR-007).
- The system never silently rewrites user-chosen weights (FR-008); it may warn.
- On any error, the offending field is named so the user can fix it without reading logs (SC-006).
