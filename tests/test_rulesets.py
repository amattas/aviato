from __future__ import annotations

from aviato.policy import load_policy, release_tag_pattern
from aviato.rulesets import render_all_rulesets


def test_rendered_tag_ruleset_uses_policy_pattern() -> None:
    policy = load_policy()
    payloads = render_all_rulesets()
    tag_rulesets = [payload for payload in payloads if payload["target"] == "tag"]

    assert tag_rulesets
    assert tag_rulesets[0]["rules"][2]["parameters"]["pattern"] == release_tag_pattern(policy)
