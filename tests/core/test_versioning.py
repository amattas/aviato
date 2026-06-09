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


def test_breaking_change_in_prose_does_not_bump_major() -> None:
    # "BREAKING CHANGE:" must be a footer, not a phrase in the body — a feat that only
    # mentions it in prose is still a minor, not an unintended major (§5.9).
    commits = ["feat: x\n\nThis change carefully avoids any BREAKING CHANGE: nothing here breaks."]
    assert classify_commits(commits) == BumpKind.MINOR


def test_indented_breaking_change_is_not_a_footer() -> None:
    # review #22: a Conventional Commits footer is at column 0; an INDENTED "BREAKING CHANGE:"
    # (e.g. inside a quoted block / code fence in the body) must NOT force a major bump.
    commits = ["feat: x\n\n    BREAKING CHANGE: this is indented, not a footer"]
    assert classify_commits(commits) == BumpKind.MINOR
    # A genuine column-0 footer still bumps major.
    assert classify_commits(["feat: x\n\nBREAKING CHANGE: real footer"]) == BumpKind.MAJOR


def test_feature_bumps_minor() -> None:
    assert classify_commits(["fix: a", "feat: b", "chore: c"]) == BumpKind.MINOR


def test_fix_only_bumps_patch() -> None:
    assert classify_commits(["fix: a", "docs: b"]) == BumpKind.PATCH


def test_non_releasable_commits_are_none() -> None:
    # non-conventional, chore-only, and empty all imply NO release (§5.9) — so the
    # chore(release) commit and empty history never loop into endless patch cuts.
    assert classify_commits(["random message"]) == BumpKind.NONE
    assert classify_commits(["chore(release): v1.2.4", "docs: x"]) == BumpKind.NONE
    assert classify_commits([]) == BumpKind.NONE


def test_next_version_applies_bump() -> None:
    # Emits a bare SemVer tag (no leading ``v``) — both tags and pins are bare.
    assert next_version("1.2.3", BumpKind.MAJOR) == "2.0.0"
    assert next_version("1.2.3", BumpKind.MINOR) == "1.3.0"
    assert next_version("1.2.3", BumpKind.PATCH) == "1.2.4"
    # A legacy ``v``-prefixed input still parses; the output is normalized to bare.
    assert next_version("v1.2.3", BumpKind.MINOR) == "1.3.0"


def test_next_version_none_is_unchanged() -> None:
    assert next_version("v1.2.3", BumpKind.NONE) == "1.2.3"
    assert next_version("1.2.3", classify_commits(["chore: x"])) == "1.2.3"


def test_next_version_from_commits_end_to_end() -> None:
    assert next_version("0.4.1", classify_commits(["feat: x"])) == "0.5.0"


def test_next_version_rejects_bad_current() -> None:
    with pytest.raises(CompatibilityError):
        next_version("nope", BumpKind.PATCH)


def test_next_version_from_prerelease_current_bumps_core() -> None:
    # A pre-release current (a policy-valid alpha/beta tag) must NOT crash; the bump
    # applies to the core X.Y.Z and drops the pre-release suffix (§5.9). The release
    # workflow's `git describe` can legitimately select such a tag.
    assert next_version("1.2.3-beta1", BumpKind.PATCH) == "1.2.4"
    assert next_version("1.2.3-alpha1", BumpKind.MINOR) == "1.3.0"
    assert next_version("1.2.3-beta2", BumpKind.MAJOR) == "2.0.0"
    # A legacy v-prefixed pre-release still parses.
    assert next_version("v1.2.3-beta1", BumpKind.PATCH) == "1.2.4"


def test_next_version_none_keeps_prerelease_for_no_release_detection() -> None:
    # NONE returns the current version unchanged (normalized to bare) so the release
    # workflow's `next == last` no-release check still fires when the last tag was a
    # pre-release — otherwise a beta with no new releasable commits would loop.
    assert next_version("1.2.3-beta1", BumpKind.NONE) == "1.2.3-beta1"
    assert next_version("v1.2.3-alpha1", BumpKind.NONE) == "1.2.3-alpha1"


def test_is_highest_orders_multi_digit_numerically_not_lexically() -> None:
    # R5-7: the parity battery only proves the inline snippet AGREES with core; if core itself
    # ordered lexically, both would agree and pass. Lock numeric ordering directly: "1.10.0" is
    # newer than "1.2.0" (10 > 2), and beta10 outranks beta2 — a string compare would invert both.
    assert is_highest("1.10.0", ["1.9.0", "1.2.0", "1.10.0"]) is True
    assert is_highest("1.2.0", ["1.10.0", "1.2.0"]) is False
    assert is_highest("1.0.0-beta10", ["1.0.0-beta2", "1.0.0-beta10"]) is True
    assert is_highest("1.0.0-beta2", ["1.0.0-beta10", "1.0.0-beta2"]) is False
