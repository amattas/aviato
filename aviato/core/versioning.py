from __future__ import annotations

import enum
import re
from collections.abc import Iterable

from .version import parse_version

_HEADER_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(?P<scope>\([^)]*\))?(?P<bang>!)?:")
_RELEASE_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta)(\d+))?$")

# Pre-release rank: a final release outranks beta, which outranks alpha (§13.2).
_PRE_RANK = {None: 2, "beta": 1, "alpha": 0}


def _release_key(tag: str) -> tuple[int, int, int, int, int] | None:
    match = _RELEASE_RE.match(tag.strip())
    if match is None:
        return None
    major, minor, patch, pre, pre_num = match.groups()
    return (int(major), int(minor), int(patch), _PRE_RANK[pre], int(pre_num or 0))


def is_highest(candidate: str, existing: Iterable[str]) -> bool:
    """True iff ``candidate`` is the highest released version among ``existing`` (§8.14/§13.2).

    Used to gate a mutable published alias (e.g. an image ``latest`` tag or docs
    alias) so a slower, older-release deploy cannot move the alias backward.
    Unparseable tags are ignored; a final release outranks its own pre-releases.
    """
    candidate_key = _release_key(candidate)
    if candidate_key is None:
        return False
    keys = [key for key in (_release_key(tag) for tag in existing) if key is not None]
    keys.append(candidate_key)
    return max(keys) == candidate_key


class BumpKind(enum.IntEnum):
    """SemVer bump levels, ordered so the highest wins (§5.9)."""

    PATCH = 1
    MINOR = 2
    MAJOR = 3


def _commit_bump(message: str) -> BumpKind:
    header = message.splitlines()[0] if message else ""
    match = _HEADER_RE.match(header.strip())
    if match is None:
        # Not a Conventional Commit header → treat as a patch-level change.
        return BumpKind.PATCH
    if match.group("bang") or "BREAKING CHANGE:" in message or "BREAKING-CHANGE:" in message:
        return BumpKind.MAJOR
    if match.group("type").lower() == "feat":
        return BumpKind.MINOR
    return BumpKind.PATCH


def classify_commits(commits: Iterable[str]) -> BumpKind:
    """Derive the highest SemVer bump implied by a set of Conventional Commits (§5.9).

    A ``!`` marker or a ``BREAKING CHANGE:`` footer is major; a ``feat`` is
    minor; anything else (including non-conventional messages) is patch.
    """
    highest = BumpKind.PATCH
    for message in commits:
        bump = _commit_bump(message)
        if bump > highest:
            highest = bump
    return highest


def next_version(current: str, bump: BumpKind) -> str:
    """Apply ``bump`` to ``current`` (``vX.Y.Z`` or ``X.Y.Z``) → ``X.Y.Z`` (§5.9)."""
    major, minor, patch = parse_version(current)
    if bump == BumpKind.MAJOR:
        return f"{major + 1}.0.0"
    if bump == BumpKind.MINOR:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"
