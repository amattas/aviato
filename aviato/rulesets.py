from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import github
from .paths import REPO_ROOT
from .policy import default_required_approvals, get_path, load_policy, load_ruleset_manifest


def _patch_branch_ruleset(payload: dict[str, Any], approvals: int) -> None:
    for rule in payload.get("rules", []):
        if rule.get("type") == "pull_request":
            parameters = rule.setdefault("parameters", {})
            parameters["required_approving_review_count"] = approvals


def _patch_tag_ruleset(payload: dict[str, Any], tag_pattern: str) -> None:
    for rule in payload.get("rules", []):
        if rule.get("type") == "tag_name_pattern":
            parameters = rule.setdefault("parameters", {})
            parameters["pattern"] = tag_pattern


def _patch_status_checks(payload: dict[str, Any], extra_contexts: list[str]) -> None:
    """Union additional required status-check contexts into the branch ruleset (§10.3/§5.6).

    The static ruleset carries only the common (language-agnostic) checks; a resolved
    profile adds its language verify job (e.g. ``ci / Python CI``) so the ruleset cannot
    enforce merge protection weaker than the profile composed for the repo.
    """
    if not extra_contexts:
        return
    for rule in payload.get("rules", []):
        if rule.get("type") == "required_status_checks":
            parameters = rule.setdefault("parameters", {})
            checks = parameters.setdefault("required_status_checks", [])
            present = {c.get("context") for c in checks}
            for context in extra_contexts:
                if context not in present:
                    checks.append({"context": context})
                    present.add(context)


def render_ruleset(
    item: dict[str, Any],
    *,
    root: Path = REPO_ROOT,
    policy: dict[str, Any] | None = None,
    required_approvals: int | None = None,
    extra_status_checks: list[str] | None = None,
) -> dict[str, Any]:
    policy = policy or load_policy(root)
    payload_path = root / item["file"]
    with payload_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    rendered = deepcopy(payload)
    target = item.get("target", rendered.get("target"))
    patch = item.get("patch", {})

    if target == "branch":
        approvals = required_approvals
        if approvals is None:
            approval_path = patch.get("required_approving_review_count")
            approvals = int(get_path(policy, approval_path)) if approval_path else default_required_approvals(policy)
        _patch_branch_ruleset(rendered, approvals)
        _patch_status_checks(rendered, extra_status_checks or [])

    if target == "tag":
        tag_path = patch.get("tag_name_pattern", "release.tag_pattern")
        _patch_tag_ruleset(rendered, str(get_path(policy, tag_path)))

    return rendered


def render_all_rulesets(
    *,
    root: Path = REPO_ROOT,
    required_approvals: int | None = None,
    extra_status_checks: list[str] | None = None,
) -> list[dict[str, Any]]:
    policy = load_policy(root)
    manifest = load_ruleset_manifest(root)
    return [
        render_ruleset(
            item,
            root=root,
            policy=policy,
            required_approvals=required_approvals,
            extra_status_checks=extra_status_checks,
        )
        for item in manifest.get("rulesets", [])
    ]


def apply_rulesets(
    slugs: list[str],
    *,
    apply: bool,
    required_approvals: int | None = None,
    extra_status_checks: list[str] | None = None,
) -> list[str]:
    payloads = render_all_rulesets(required_approvals=required_approvals, extra_status_checks=extra_status_checks)
    messages: list[str] = []
    for slug in slugs:
        for payload in payloads:
            messages.append(github.upsert_ruleset(slug, payload, apply=apply))
    return messages
