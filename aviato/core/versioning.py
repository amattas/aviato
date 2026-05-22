from __future__ import annotations

import enum
import re
from collections.abc import Iterable

from .errors import CompatibilityError

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
    """SemVer bump levels, ordered so the highest wins (§5.9). NONE = no release."""

    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3


def _has_breaking_footer(message: str) -> bool:
    """True iff a line is a ``BREAKING CHANGE:`` footer (per Conventional Commits).

    The token must BEGIN a footer line — a mid-line mention in prose body text does
    not count, so it cannot force an unintended major bump.
    """
    return any(line.lstrip().startswith(("BREAKING CHANGE:", "BREAKING-CHANGE:")) for line in message.splitlines())


def _commit_bump(message: str) -> BumpKind:
    header = message.splitlines()[0] if message else ""
    match = _HEADER_RE.match(header.strip())
    if match is None:
        # Not a Conventional Commit header → not a releasable change.
        return BumpKind.NONE
    if match.group("bang") or _has_breaking_footer(message):
        return BumpKind.MAJOR
    commit_type = match.group("type").lower()
    if commit_type == "feat":
        return BumpKind.MINOR
    if commit_type in ("fix", "perf"):
        return BumpKind.PATCH
    # chore/docs/style/refactor/test/ci/build/etc. do not, on their own, cut a
    # release — so the release commit (chore) and empty history NEVER loop (§5.9).
    return BumpKind.NONE


def classify_commits(commits: Iterable[str]) -> BumpKind:
    """Derive the highest SemVer bump implied by a set of Conventional Commits (§5.9).

    A ``!``/``BREAKING CHANGE`` is major; ``feat`` is minor; ``fix``/``perf`` is
    patch; anything else (including non-conventional or no commits) implies NO
    release (``NONE``).
    """
    highest = BumpKind.NONE
    for message in commits:
        bump = _commit_bump(message)
        if bump > highest:
            highest = bump
    return highest


def next_version(current: str, bump: BumpKind) -> str:
    """Apply ``bump`` to ``current`` → the next bare ``X.Y.Z`` (§5.9, §6.1 pin format).

    Tags and pins are bare SemVer (no leading ``v``); a legacy ``v``-prefixed
    ``current`` still parses but the result is normalized to bare. ``current`` may
    also be a policy-valid pre-release tag (``X.Y.Z-alphaN``/``-betaN``) — the
    release workflow's ``git describe`` can select one — in which case a release
    bump applies to the core ``X.Y.Z`` and drops the pre-release suffix. ``NONE``
    returns the current version unchanged (suffix preserved, normalized to bare),
    so a caller can detect "no release" by comparing to the current tag.
    """
    match = _RELEASE_RE.match(current.strip())
    if match is None:
        raise CompatibilityError(f"not a release version: {current!r}")
    major, minor, patch, pre, pre_num = match.groups()
    major, minor, patch = int(major), int(minor), int(patch)
    if bump == BumpKind.MAJOR:
        return f"{major + 1}.0.0"
    if bump == BumpKind.MINOR:
        return f"{major}.{minor + 1}.0"
    if bump == BumpKind.PATCH:
        return f"{major}.{minor}.{patch + 1}"
    suffix = f"-{pre}{pre_num}" if pre is not None else ""
    return f"{major}.{minor}.{patch}{suffix}"
