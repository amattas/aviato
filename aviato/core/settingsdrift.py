from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ADDITIVE = "additive"
DESTRUCTIVE = "destructive"


@dataclass
class SettingsDiff:
    changes: dict[str, str] = field(default_factory=dict)

    @property
    def destructive(self) -> bool:
        return any(kind == DESTRUCTIVE for kind in self.changes.values())


def _classify_value_change(desired: Any, live: Any) -> str:
    """Classify a changed value as additive or destructive (§5.6, fail-safe)."""
    # Booleans first (bool is a subclass of int).
    if isinstance(desired, bool) or isinstance(live, bool):
        if isinstance(desired, bool) and isinstance(live, bool):
            return ADDITIVE if (desired and not live) else DESTRUCTIVE
        return DESTRUCTIVE
    if isinstance(desired, (int, float)) and isinstance(live, (int, float)):
        return ADDITIVE if desired > live else DESTRUCTIVE
    # Ambiguous / unrecognized change → destructive (fail-safe).
    return DESTRUCTIVE


def classify_settings(*, desired: dict[str, Any], live: dict[str, Any]) -> SettingsDiff:
    """Diff desired vs live protected settings, classifying each change (§5.6).

    A change is **additive** only if it introduces a new constraint with no
    loss (a new key, or a strengthened value). It is **destructive** if it
    removes, weakens, or replaces an existing value. Ambiguous or unrecognized
    changes classify as destructive (fail-safe).
    """
    diff = SettingsDiff()
    for key in sorted(set(desired) | set(live)):
        in_desired = key in desired
        in_live = key in live
        if in_desired and not in_live:
            diff.changes[key] = ADDITIVE
        elif in_live and not in_desired:
            diff.changes[key] = DESTRUCTIVE
        else:
            if desired[key] == live[key]:
                continue
            diff.changes[key] = _classify_value_change(desired[key], live[key])
    return diff
