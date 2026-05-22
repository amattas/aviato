from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ADDITIVE = "additive"
DESTRUCTIVE = "destructive"


@dataclass
class SettingsDiff:
    changes: dict[str, str] = field(default_factory=dict)
    # Per changed key, the actual {"desired": ..., "live": ...} values. Consent is
    # bound to these concrete values, not just the additive/destructive kind (§6.4),
    # so 1->2 and 1->5 are distinct changes that require distinct consent.
    values: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def destructive(self) -> bool:
        return any(kind == DESTRUCTIVE for kind in self.changes.values())


def _hashable(value: Any) -> Any:
    """Best-effort hashable view of a list element for subset comparison."""
    if isinstance(value, (list, tuple)):
        return tuple(_hashable(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    return value


def _classify_value_change(desired: Any, live: Any) -> str:
    """Classify a changed value as additive or destructive (§5.6, fail-safe)."""
    # Booleans first (bool is a subclass of int).
    if isinstance(desired, bool) or isinstance(live, bool):
        if isinstance(desired, bool) and isinstance(live, bool):
            return ADDITIVE if (desired and not live) else DESTRUCTIVE
        return DESTRUCTIVE
    if isinstance(desired, (int, float)) and isinstance(live, (int, float)):
        return ADDITIVE if desired > live else DESTRUCTIVE
    # Lists (e.g. required_status_checks): a superset only ADDS constraints, so it is
    # additive; dropping or replacing any element loses a constraint (§5.6).
    if isinstance(desired, list) and isinstance(live, list):
        live_set = {_hashable(v) for v in live}
        desired_set = {_hashable(v) for v in desired}
        return ADDITIVE if live_set.issubset(desired_set) else DESTRUCTIVE
    # Ambiguous / unrecognized change → destructive (fail-safe).
    return DESTRUCTIVE


def classify_settings(*, desired: dict[str, Any], live: dict[str, Any]) -> SettingsDiff:
    """Diff desired vs live protected settings, classifying each change (§5.6).

    A change is **additive** only if it introduces a new constraint with no
    loss (a new key, a strengthened value, or a superset list). It is
    **destructive** if it removes, weakens, or replaces an existing value.
    Ambiguous or unrecognized changes classify as destructive (fail-safe). The
    concrete desired/live values are recorded for content-bound consent (§6.4).
    """
    diff = SettingsDiff()

    def _record(key: str, kind: str, desired_value: Any, live_value: Any) -> None:
        diff.changes[key] = kind
        diff.values[key] = {"desired": desired_value, "live": live_value}

    for key in sorted(set(desired) | set(live)):
        in_desired = key in desired
        in_live = key in live
        if in_desired and not in_live:
            _record(key, ADDITIVE, desired[key], None)
        elif in_live and not in_desired:
            _record(key, DESTRUCTIVE, None, live[key])
        else:
            if desired[key] == live[key]:
                continue
            _record(key, _classify_value_change(desired[key], live[key]), desired[key], live[key])
    return diff
