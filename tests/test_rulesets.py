from __future__ import annotations

from aviato.policy import load_policy, release_tag_pattern
from aviato.rulesets import render_all_rulesets


def test_rendered_tag_ruleset_uses_policy_pattern() -> None:
    policy = load_policy()
    payloads = render_all_rulesets()
    tag_rulesets = [payload for payload in payloads if payload["target"] == "tag"]

    assert tag_rulesets
    assert tag_rulesets[0]["rules"][2]["parameters"]["pattern"] == release_tag_pattern(policy)


def _status_contexts(payloads: list) -> set[str]:
    contexts: set[str] = set()
    for payload in payloads:
        for rule in payload.get("rules", []):
            if rule.get("type") == "required_status_checks":
                contexts.update(c["context"] for c in rule["parameters"]["required_status_checks"])
    return contexts


def test_ruleset_without_profile_has_only_common_checks() -> None:
    contexts = _status_contexts(render_all_rulesets())
    assert "ci / Python CI" not in contexts
    assert "common-lint / Common lint" in contexts


def test_ruleset_with_profile_injects_language_verify_check() -> None:
    # #7: apply/render-rulesets must include the resolved profile's language verify
    # job so the branch ruleset is not weaker than the composed profile.
    contexts = _status_contexts(render_all_rulesets(extra_status_checks=["ci / Python CI"]))
    assert "ci / Python CI" in contexts
    assert "common-lint / Common lint" in contexts
    # idempotent: a re-injected common check is not duplicated
    payloads = render_all_rulesets(extra_status_checks=["common-lint / Common lint"])
    rule = next(r for p in payloads for r in p.get("rules", []) if r.get("type") == "required_status_checks")
    common = [c for c in rule["parameters"]["required_status_checks"] if c["context"] == "common-lint / Common lint"]
    assert len(common) == 1
