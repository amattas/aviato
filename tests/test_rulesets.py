from __future__ import annotations

import copy
from typing import Any

import yaml

from aviato import github
from aviato.paths import POLICY_DATA_ROOT
from aviato.policy import load_policy, release_tag_pattern
from aviato.rulesets import render_all_rulesets, ruleset_content_drift

Ruleset = dict[str, Any]


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


def test_tag_ruleset_excludes_floating_major_aliases_for_realistic_widths() -> None:
    # §5.9/§6.1: the floating-major alias is a BARE integer of arbitrary width
    # (a 5-digit major like 10000 is valid SemVer). fnmatch cannot express
    # "digits-only of any length" (``*`` also matches the dots in 1.2.3), so the
    # exclude list enumerates a generous range of fixed widths. A previously-finite
    # 1–4 digit list would reject a 10000.0.0 release's floating tag.
    payloads = render_all_rulesets()
    tag = next(p for p in payloads if p["target"] == "tag")
    exclude = tag["conditions"]["ref_name"]["exclude"]
    for width in range(1, 10):
        pattern = "refs/tags/" + "[0-9]" * width
        assert pattern in exclude, f"floating major width {width} not excluded ({pattern})"
    assert "refs/tags/v[0-9]" not in exclude


def _status_contexts(payloads: list[Ruleset]) -> set[str]:
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


def test_every_rendered_branch_ruleset_has_exact_codeql_merge_gate() -> None:
    pipeline = yaml.safe_load((POLICY_DATA_ROOT / "pipelines.yaml").read_text(encoding="utf-8"))["security-baseline"]
    expected_tool = pipeline["code_scanning_tool"]
    assert expected_tool == github.EXPECTED_CODEQL_RULE
    payloads = render_all_rulesets()
    branches = [payload for payload in payloads if payload["target"] == "branch"]
    assert branches
    for branch in branches:
        rules = [rule for rule in branch["rules"] if rule["type"] == "code_scanning"]
        assert len(rules) == 1
        assert rules[0]["parameters"]["code_scanning_tools"] == [expected_tool]


def test_codeql_ruleset_threshold_removal_or_weakening_is_drift() -> None:
    branch = next(payload for payload in render_all_rulesets() if payload["target"] == "branch")
    assert ruleset_content_drift(branch, copy.deepcopy(branch)) is False

    missing = copy.deepcopy(branch)
    missing["rules"] = [rule for rule in missing["rules"] if rule["type"] != "code_scanning"]
    assert ruleset_content_drift(branch, missing) is True

    weakened = copy.deepcopy(branch)
    codeql = next(rule for rule in weakened["rules"] if rule["type"] == "code_scanning")
    codeql["parameters"]["code_scanning_tools"][0]["security_alerts_threshold"] = "critical"
    assert ruleset_content_drift(branch, weakened) is True


def _approval_counts(payloads: list[Ruleset]) -> list[int]:
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


def _branch_and_tag() -> tuple[Ruleset, Ruleset]:
    import copy

    from aviato.rulesets import render_all_rulesets

    rendered = render_all_rulesets(extra_status_checks=["ci / Python CI"])
    branch = next(r for r in rendered if r["target"] == "branch")
    tag = next(r for r in rendered if r["target"] == "tag")
    return copy.deepcopy(branch), copy.deepcopy(tag)


def test_ruleset_content_drift_none_when_live_matches() -> None:
    from aviato.rulesets import ruleset_content_drift

    branch, tag = _branch_and_tag()
    assert ruleset_content_drift(branch, branch) is False
    assert ruleset_content_drift(tag, tag) is False


def test_ruleset_content_drift_ignores_github_added_metadata() -> None:
    # §5.6: GitHub returns extra fields (id, _links, source, defaulted params) — these must not
    # read as drift. _subset_match compares only what Aviato rendered.
    import copy

    from aviato.rulesets import ruleset_content_drift

    branch, _ = _branch_and_tag()
    live = copy.deepcopy(branch)
    live["id"] = 42
    live["_links"] = {"self": {"href": "..."}}
    live["created_at"] = "2026-01-01"
    for rule in live["rules"]:
        rule.setdefault("parameters", {})["github_added_default"] = "x"
    live["rules"].append({"type": "creation"})  # a benign EXTRA live rule
    assert ruleset_content_drift(branch, live) is False


def test_ruleset_content_drift_detects_disabled_enforcement() -> None:
    from aviato.rulesets import ruleset_content_drift

    branch, _ = _branch_and_tag()
    live = {**branch, "enforcement": "disabled"}
    assert ruleset_content_drift(branch, live) is True
    live_eval = {**branch, "enforcement": "evaluate"}
    assert ruleset_content_drift(branch, live_eval) is True


def test_ruleset_content_drift_detects_weakened_tag_pattern() -> None:
    import copy

    from aviato.rulesets import ruleset_content_drift

    _, tag = _branch_and_tag()
    live = copy.deepcopy(tag)
    for rule in live["rules"]:
        if rule.get("type") == "tag_name_pattern":
            rule["parameters"]["pattern"] = ".*"  # permissive
    assert ruleset_content_drift(tag, live) is True


def test_ruleset_content_drift_detects_lowered_approvals_and_missing_rule() -> None:
    import copy

    from aviato.rulesets import ruleset_content_drift

    branch, _ = _branch_and_tag()
    lowered = copy.deepcopy(branch)
    for rule in lowered["rules"]:
        if rule.get("type") == "pull_request":
            rule["parameters"]["required_approving_review_count"] = 0
    assert ruleset_content_drift(branch, lowered) is True

    missing_rule = copy.deepcopy(branch)
    missing_rule["rules"] = [r for r in missing_rule["rules"] if r.get("type") != "non_fast_forward"]
    assert ruleset_content_drift(branch, missing_rule) is True


def test_ruleset_content_drift_detects_dropped_required_status_check() -> None:
    import copy

    from aviato.rulesets import ruleset_content_drift

    branch, _ = _branch_and_tag()
    live = copy.deepcopy(branch)
    for rule in live["rules"]:
        if rule.get("type") == "required_status_checks":
            rule["parameters"]["required_status_checks"] = [{"context": "common-lint / Common lint"}]  # dropped ci
    assert ruleset_content_drift(branch, live) is True


def test_drifted_ruleset_names_flags_missing_and_drifted() -> None:
    import copy

    from aviato.rulesets import drifted_ruleset_names

    branch, tag = _branch_and_tag()
    # Live has the branch ruleset clean, the tag ruleset disabled, and is MISSING nothing extra.
    live_tag_disabled = {**copy.deepcopy(tag), "enforcement": "disabled"}
    drifted = drifted_ruleset_names([branch, tag], [copy.deepcopy(branch), live_tag_disabled])
    assert drifted == [tag["name"]]
    # A missing ruleset (only branch live) → both the absent tag is flagged.
    drifted_missing = drifted_ruleset_names([branch, tag], [copy.deepcopy(branch)])
    assert drifted_missing == [tag["name"]]
    # All present + clean → none.
    assert drifted_ruleset_names([branch, tag], [copy.deepcopy(branch), copy.deepcopy(tag)]) == []


def test_ruleset_content_drift_detects_added_bypass_actor() -> None:
    # §5.6 (M-B): a live ruleset that adds a bypass_actor (skips ALL rules) must drift — Aviato's
    # rulesets grant none, so any live bypass is a weakening.
    import copy

    from aviato.rulesets import ruleset_content_drift

    branch, _ = _branch_and_tag()
    live = copy.deepcopy(branch)
    live["bypass_actors"] = [{"actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always"}]
    assert ruleset_content_drift(branch, live) is True
    # No bypass on either side → no false drift.
    assert ruleset_content_drift(branch, copy.deepcopy(branch)) is False


def test_policy_ruleset_data_ships_in_the_package() -> None:
    # H-A: the policy/ruleset DATA must live inside the package (POLICY_DATA_ROOT) so it ships in
    # the wheel — a pip-installed aviato renders rulesets without a source checkout (§5.6/§11.3).
    from aviato.paths import POLICY_DATA_ROOT
    from aviato.rulesets import render_all_rulesets

    assert (POLICY_DATA_ROOT / "policy.yml").is_file()
    assert (POLICY_DATA_ROOT / "rulesets.yml").is_file()
    assert list((POLICY_DATA_ROOT / "rulesets").glob("*.json"))
    # And rendering resolves entirely from the packaged location (no repo-root dependency).
    assert len(render_all_rulesets()) == 2


def test_drift_distinguishes_target() -> None:
    # R3-10: a live ruleset sharing a name but a different target must NOT satisfy the desired one.
    from aviato.rulesets import drifted_ruleset_names

    desired = [{"name": "X", "target": "branch", "enforcement": "active", "rules": []}]
    live_wrong_target = [{"name": "X", "target": "tag", "enforcement": "active", "rules": []}]
    assert drifted_ruleset_names(desired, live_wrong_target) == ["X"]  # missing the branch one
    live_right = [{"name": "X", "target": "branch", "enforcement": "active", "rules": []}]
    assert drifted_ruleset_names(desired, live_right) == []


def test_render_rejects_unknown_patch_key() -> None:
    # R3-9: an unknown patch key (typo) must fail loud, not silently leave a value un-injected.
    import pytest as _pytest

    from aviato.rulesets import render_ruleset

    with _pytest.raises(ValueError, match="unknown patch key"):
        render_ruleset(
            {"file": "rulesets/release-tag-format.json", "target": "tag", "patch": {"tag_naem_pattern": "x"}}
        )


def test_missing_tag_metadata_rule_is_non_clean_drift() -> None:
    from aviato.rulesets import drifted_ruleset_names

    desired = next(payload for payload in render_all_rulesets() if payload["target"] == "tag")
    degraded = copy.deepcopy(desired)
    degraded["rules"] = [rule for rule in degraded["rules"] if rule["type"] != "tag_name_pattern"]

    assert drifted_ruleset_names([desired], [degraded]) == [desired["name"]]
