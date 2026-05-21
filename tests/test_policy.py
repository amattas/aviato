from __future__ import annotations

import re

from aviato.policy import load_policy, release_tag_pattern


def test_release_tag_examples_match_policy() -> None:
    policy = load_policy()
    pattern = re.compile(release_tag_pattern(policy))

    examples = policy["release"]["examples"]
    assert all(pattern.fullmatch(value) for value in examples["valid"])
    assert not any(pattern.fullmatch(value) for value in examples["invalid"])
