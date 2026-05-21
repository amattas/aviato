from __future__ import annotations

import pytest

from aviato.core.errors import CompatibilityError
from aviato.core.versioning import BumpKind, classify_commits, is_highest, next_version


def test_is_highest_true_when_candidate_is_max() -> None:
    assert is_highest("1.2.0", ["1.0.0", "1.1.5", "1.2.0"]) is True


def test_is_highest_false_when_older_release_exists() -> None:
    assert is_highest("1.1.0", ["1.0.0", "1.2.0", "1.1.0"]) is False


def test_release_outranks_its_prerelease() -> None:
    # 1.2.0 (release) is higher than 1.2.0-beta2 / 1.2.0-alpha1
    assert is_highest("1.2.0", ["1.2.0-alpha1", "1.2.0-beta2", "1.2.0"]) is True
    assert is_highest("1.2.0-beta2", ["1.2.0-beta2", "1.2.0"]) is False


def test_prerelease_ordering_beta_above_alpha() -> None:
    assert is_highest("1.2.0-beta1", ["1.2.0-alpha9", "1.2.0-beta1"]) is True


def test_is_highest_ignores_unparseable_tags() -> None:
    assert is_highest("1.0.0", ["garbage", "v-bad", "1.0.0"]) is True


def test_is_highest_candidate_not_in_list_still_compares() -> None:
    assert is_highest("2.0.0", ["1.9.9"]) is True
    assert is_highest("1.0.0", ["1.9.9"]) is False


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
