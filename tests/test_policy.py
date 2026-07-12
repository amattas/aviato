from __future__ import annotations

import re

import pytest

from aviato.policy import library_repository, load_policy, release_tag_pattern


def test_release_tag_examples_match_policy() -> None:
    policy = load_policy()
    pattern = re.compile(release_tag_pattern(policy))

    examples = policy["release"]["examples"]
    assert all(pattern.fullmatch(value) for value in examples["valid"])
    assert not any(pattern.fullmatch(value) for value in examples["invalid"])


def test_required_approvals_rejects_boolean() -> None:
    # R3-17: bool is an int subclass; `true` must NOT be accepted and rendered as 1.
    import pytest as _pytest

    from aviato.policy import default_required_approvals

    with _pytest.raises(ValueError):
        default_required_approvals({"branch": {"required_approvals_default": True}})
    assert default_required_approvals({"branch": {"required_approvals_default": 2}}) == 2


@pytest.mark.parametrize(
    "value",
    [
        "./.",
        "../repo",
        "-owner/repo",
        "owner/-repo",
        " owner/repo",
        "owner/repo ",
        "owner/repo\n",
        "owner/repo?ref=main",
        "owner/repo#fragment",
        "owner/repo/extra",
    ],
)
def test_library_repository_rejects_noncanonical_slug(value: str) -> None:
    with pytest.raises(ValueError, match="owner/repository"):
        library_repository({"library": {"repository": value}})


def test_library_repository_accepts_canonical_slug() -> None:
    assert library_repository({"library": {"repository": "owner-name/repo.name"}}) == "owner-name/repo.name"
