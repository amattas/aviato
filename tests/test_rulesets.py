from __future__ import annotations

from aviato.policy import load_policy, release_tag_pattern
from aviato.rulesets import render_all_rulesets


def test_rendered_tag_ruleset_uses_policy_pattern() -> None:
    policy = load_policy()
    payloads = render_all_rulesets()
    tag_rulesets = [payload for payload in payloads if payload["target"] == "tag"]

    assert tag_rulesets
    assert tag_rulesets[0]["rules"][2]["parameters"]["pattern"] == release_tag_pattern(policy)


def test_tag_ruleset_excludes_bare_floating_major_aliases() -> None:
    # §5.9: the release workflow pushes a BARE floating-major tag (e.g. "1") as a
    # mutable pointer. The tag ruleset must EXCLUDE such aliases from the exact-X.Y.Z
    # name pattern, or the `git push -f origin 1` is rejected and floating-major
    # advancement breaks. The legacy v-prefixed excludes no longer match a bare alias.
    payloads = render_all_rulesets()
    tag = next(p for p in payloads if p["target"] == "tag")
    exclude = tag["conditions"]["ref_name"]["exclude"]
    assert "refs/tags/[0-9]" in exclude
    assert "refs/tags/[0-9][0-9]" in exclude
    assert "refs/tags/v[0-9]" not in exclude


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


def _approval_counts(payloads: list) -> list[int]:
    counts: list[int] = []
    for payload in payloads:
        for rule in payload.get("rules", []):
            params = rule.get("parameters", {})
            if "required_approving_review_count" in params:
                counts.append(params["required_approving_review_count"])
    return counts


def test_required_approvals_zero_override_propagates() -> None:
    # The solo-repo override must land as a literal 0, not silently fall back to the
    # policy default — `0` is falsy, so this guards the `is None` gating.
    counts = _approval_counts(render_all_rulesets(required_approvals=0))
    assert counts
    assert all(c == 0 for c in counts)


def test_required_approvals_default_uses_policy() -> None:
    from aviato.policy import default_required_approvals, load_policy

    expected = default_required_approvals(load_policy())
    counts = _approval_counts(render_all_rulesets())
    assert counts
    assert all(c == expected for c in counts)
