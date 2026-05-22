from __future__ import annotations

import re

from .errors import CompatibilityError

_EXACT_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_MAJOR_RE = re.compile(r"^v?(\d+)$")

Version = tuple[int, int, int]


def parse_version(value: str) -> Version:
    """Parse an exact ``vX.Y.Z`` (or ``X.Y.Z``) version into a comparable tuple."""
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

    The managed marker may record either an exact version (``vX.Y.Z``) or a
    floating pin (``vX``); a floating ``vX`` floors to ``X.0.0`` (§2.6, §6.2).
    """
    try:
        return parse_version(value)
    except CompatibilityError:
        return (_pinned_major(value), 0, 0)


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
