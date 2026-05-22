from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

ADDITIVE = "additive"
DESTRUCTIVE = "destructive"

# Length (in hex chars) of the truncated SHA-256 used as a settings-diff identity.
# Bounded so the binding's consent label (prefix + id) fits the hosting platform's
# label-name limit; see diff_identity. 128 bits is ample collision resistance here.
CONSENT_ID_HEX_LEN = 32


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


def diff_identity(diff: SettingsDiff) -> str:
    """A stable, content-bound identity for a settings diff (§6.4 consent binding).

    Hashes the changed keys together with their classification AND their concrete
    desired/live values, so consent for ``required_reviews: 1 -> 2`` does not match
    ``required_reviews: 1 -> 5`` (a different change needs different consent, §8.3).
    """
    payload = {
        key: {
            "kind": kind,
            "desired": diff.values.get(key, {}).get("desired"),
            "live": diff.values.get(key, {}).get("live"),
        }
        for key, kind in diff.changes.items()
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    # The identity is carried as a segment of the consent-grant label a human applies to the
    # tracking issue (§6.4). Hosting platforms cap label-name length (GitHub: 50 chars), and
    # the binding prefixes this id (e.g. "aviato-consent:"), so the id MUST stay short enough
    # that prefix+id fits — otherwise the label can never be created and the §5.7 gate becomes
    # unreachable. 32 hex chars = 128 bits keeps collision resistance far beyond what the tiny
    # space of distinct settings diffs needs, while leaving ample room under the limit.
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:CONSENT_ID_HEX_LEN]


def _hashable(value: Any) -> Any:
    """Best-effort hashable view of a list element for subset comparison."""
    if isinstance(value, (list, tuple)):
        return tuple(_hashable(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    return value


def _classify_value_change(desired: Any, live: Any) -> str:
    """Classify a changed value as additive or destructive (§5.6).

    This assumes the flat settings model is framed so that "more True / higher /
    superset = more protection" — which the day-zero baseline keys are by
    construction (e.g. ``block_force_push``, ``required_reviews``,
    ``required_status_checks``). The classification only labels the report; the
    operator gate (§5.7) fail-closes regardless, and any unrecognized/ambiguous
    change falls through to destructive (the safe default).
    """
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
