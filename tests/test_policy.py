from __future__ import annotations

import re

from aviato.policy import load_policy, release_tag_pattern


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
