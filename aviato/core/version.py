from __future__ import annotations

import re
from collections.abc import Sequence

from .errors import CompatibilityError

_EXACT_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_MAJOR_RE = re.compile(r"^v?(\d+)$")

Version = tuple[int, int, int]


def parse_version(value: str) -> Version:
    """Parse an exact ``X.Y.Z`` version into a comparable tuple (a legacy ``v`` prefix is tolerated)."""
    match = _EXACT_RE.match(value.strip())
    if not match:
        raise CompatibilityError(f"not an exact version: {value!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _pinned_major(pinned: str) -> int:
    pinned = pinned.strip()
    exact = _EXACT_RE.match(pinned)
    if exact:
        return int(exact.group(1))
    major = _MAJOR_RE.match(pinned)
    if major:
        return int(major.group(1))
    raise CompatibilityError(f"not a version pin: {pinned!r}")


def _as_lower_bound(value: str) -> Version:
    """Coerce an exact version or a floating major reference to a comparable lower bound.

    The managed marker may record either an exact version (``X.Y.Z``) or a
    floating pin (``N``); a floating ``N`` floors to ``N.0.0`` (§2.6, §6.2).
    A legacy ``v`` prefix on either form is tolerated for backward compatibility.
    """
    try:
        return parse_version(value)
    except CompatibilityError:
        return (_pinned_major(value), 0, 0)


def normalize_pin(value: str) -> str:
    """Canonicalize a version pin to its bare-SemVer form (§6.1).

    A recognized pin is an exact ``X.Y.Z`` or a floating major ``N``; a legacy
    leading ``v`` is tolerated on input but **stripped** so it is never emitted
    into a declaration or managed marker. Raises :class:`CompatibilityError` if
    ``value`` is not a recognized pin (so an operator typo cannot be persisted).
    """
    stripped = value.strip()
    if not is_known_version_pin(stripped):
        raise CompatibilityError(f"not a version pin: {value!r}")
    return stripped[1:] if stripped[:1] == "v" else stripped


def is_known_version_pin(value: str) -> bool:
    """True iff ``value`` is a recognized version pin: an exact ``X.Y.Z`` or a floating
    major ``N`` (a legacy ``v`` prefix tolerated). A managed marker recording an
    unrecognized version cannot be reasoned about for compatibility, so diagnosis
    classifies it as dirty-drift rather than silently regenerating it (§5.4)."""
    try:
        _as_lower_bound(value)
        return True
    except CompatibilityError:
        return False


def most_restrictive_recorded(values: Sequence[str]) -> str:
    """The §2.6 lower bound across multiple recorded markers.

    Compatibility requires the tool to be ``>=`` **every** marker's recorded
    version, i.e. ``>=`` their maximum — so the binding lower bound is the
    **highest** recorded version, not the first one encountered (which could hide
    a higher, incompatible marker behind a compatible one). An **unrecognized**
    marker is returned as-is so :func:`is_compatible` raises and the caller fails
    closed on it (§2.6/§2.7), never silently dropping it from the comparison.

    ``values`` must be non-empty; the caller falls back to the declared pin when
    a Consumer has no managed markers.
    """
    if not values:
        raise CompatibilityError("no recorded marker versions to compare")
    unrecognized = [value for value in values if not is_known_version_pin(value)]
    if unrecognized:
        return unrecognized[0]
    return max(values, key=_as_lower_bound)


def is_compatible(*, tool: str, pinned: str, recorded: str) -> bool:
    """The §2.6 compatibility relation.

    The acting tool is compatible with a Consumer's pin iff the tool's major
    equals the pinned major **and** the tool's version is ``>=`` the version
    recorded in the Consumer's managed markers. The recorded value may be an exact
    version or a floating pin (floored to ``X.0.0``).
    """
    tool_version = parse_version(tool)
    recorded_version = _as_lower_bound(recorded)
    return tool_version[0] == _pinned_major(pinned) and tool_version >= recorded_version
