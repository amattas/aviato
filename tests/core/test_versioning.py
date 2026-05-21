from __future__ import annotations

import pytest

from aviato.core.errors import CompatibilityError
from aviato.core.versioning import BumpKind, classify_commits, next_version


def test_breaking_change_bumps_major() -> None:
    commits = ["feat: a", "fix: b", "feat!: drop legacy api"]
    assert classify_commits(commits) == BumpKind.MAJOR


def test_breaking_change_footer_bumps_major() -> None:
    commits = ["fix: a\n\nBREAKING CHANGE: removed thing"]
    assert classify_commits(commits) == BumpKind.MAJOR


def test_feature_bumps_minor() -> None:
    assert classify_commits(["fix: a", "feat: b", "chore: c"]) == BumpKind.MINOR


def test_fix_only_bumps_patch() -> None:
    assert classify_commits(["fix: a", "docs: b"]) == BumpKind.PATCH


def test_no_conventional_commits_is_patch() -> None:
    assert classify_commits(["random message"]) == BumpKind.PATCH


def test_next_version_applies_bump() -> None:
    assert next_version("1.2.3", BumpKind.MAJOR) == "2.0.0"
    assert next_version("1.2.3", BumpKind.MINOR) == "1.3.0"
    assert next_version("1.2.3", BumpKind.PATCH) == "1.2.4"
    assert next_version("v1.2.3", BumpKind.MINOR) == "1.3.0"


def test_next_version_from_commits_end_to_end() -> None:
    assert next_version("0.4.1", classify_commits(["feat: x"])) == "0.5.0"


def test_next_version_rejects_bad_current() -> None:
    with pytest.raises(CompatibilityError):
        next_version("nope", BumpKind.PATCH)
