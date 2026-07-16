from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

# R7-4-RULESET-DRIFT (documented asymmetry): `_subset_match` falls through to strict scalar
# equality (e.g. `required_approving_review_count`), so a manually-tightened LIVE value (5 against
# desired 2) reports as drift, and a subsequent `apply-rulesets --apply` would LOOSEN it back to
# the desired value. This is INTENTIONALLY narrower than settings-drift's additive/destructive
# classifier (which treats `live > desired` as additive). The reason: apply-rulesets is an
# operator-DIRECT provisioning command (warns explicitly on invocation, see cli.py — "not the
# §5.7 drift/consent flow"). The operator is asserting "the manifest is the desired state, period",
# so a stricter-live mismatch is a real divergence the operator should review (then either bump
# the manifest or accept the loosening). Loosening is not silent — the message in `messages`
# describes the upsert. If you want the settings-drift semantics here, route the scalar compare
# through `settingsdrift._classify_value_change` (deliberately NOT done because the manifest is the
# single source of truth in the operator-direct path).
from . import github
from .core.ports import RulesetApplyResult
from .core.ruleset_plan import security_payload
from .policy import default_required_approvals, get_path, load_policy, load_ruleset_manifest

# R3-9: the patch keys a manifest entry may declare. An unknown key (typo) would be silently
# ignored and render a weakened payload, so render_ruleset rejects anything outside this set.
_KNOWN_PATCH_KEYS = frozenset({"required_approving_review_count", "tag_name_pattern"})


def _patch_branch_ruleset(payload: dict[str, Any], approvals: int) -> None:
    injected = False
    for rule in payload.get("rules", []):
        if rule.get("type") == "pull_request":
            parameters = rule.setdefault("parameters", {})
            parameters["required_approving_review_count"] = approvals
            injected = True
    # R3-9: a branch ruleset template missing its pull_request rule would render with NO approval
    # requirement — a silently weakened payload. Fail loud instead (§5.6/§8.10).
    if not injected:
        raise ValueError("branch ruleset has no pull_request rule to inject required_approving_review_count into")


def _patch_tag_ruleset(payload: dict[str, Any], tag_pattern: str) -> None:
    injected = False
    for rule in payload.get("rules", []):
        if rule.get("type") == "tag_name_pattern":
            parameters = rule.setdefault("parameters", {})
            parameters["pattern"] = tag_pattern
            injected = True
    if not injected:
        raise ValueError("tag ruleset has no tag_name_pattern rule to inject the release pattern into")


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
    root: Path,
    policy: dict[str, Any] | None = None,
    required_approvals: int | None = None,
    extra_status_checks: list[str] | None = None,
) -> dict[str, Any]:
    policy = policy or load_policy(root=root)
    payload_path = root / item["file"]
    with payload_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    rendered = deepcopy(payload)
    target = item.get("target", rendered.get("target"))
    patch = item.get("patch", {})
    # R3-9: an unknown patch key (a typo in rulesets.yml) would be silently ignored, leaving the
    # intended value un-injected. Reject it so a manifest mistake fails loud, not silently weakens.
    unknown_patch = set(patch) - _KNOWN_PATCH_KEYS
    if unknown_patch:
        raise ValueError(f"ruleset {item.get('file')!r} has unknown patch key(s) {sorted(unknown_patch)}")

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

    return cast(dict[str, Any], rendered)


def _subset_match(desired: Any, live: Any) -> bool:
    """True if everything ``desired`` specifies is present-and-equal in ``live`` (recursively).

    Compares ONLY what Aviato renders, so GitHub-added fields/defaults in ``live`` are ignored
    (no false drift from platform metadata). For lists, every desired element must subset-match
    SOME live element (order-insensitive) — so a removed/weakened required item (a dropped status
    check, a changed tag pattern, a lowered approval count) is drift, while a benign live ADDITION
    is not. Same additive-vs-destructive posture as settings drift (§5.6).
    """
    if isinstance(desired, dict):
        return isinstance(live, dict) and all(k in live and _subset_match(v, live[k]) for k, v in desired.items())
    if isinstance(desired, list):
        return isinstance(live, list) and all(any(_subset_match(d, item) for item in live) for d in desired)
    return bool(desired == live)


def ruleset_content_drift(desired: dict[str, Any], live: dict[str, Any], *, default_branch: str = "main") -> bool:
    """True if a live ruleset has drifted from the rendered desired payload (§5.6).

    Catches the security-relevant divergences: a DISABLED/evaluate ruleset (``enforcement`` no
    longer ``active``), an added ``bypass_actors`` entry (an actor that can skip ALL rules — incl.
    admin enforcement, so this also backs the §2.13 enforce_admins posture), a MISSING required
    rule type, and a WEAKENED rule parameter (e.g. a permissive ``tag_name_pattern`` or a lowered
    ``required_approving_review_count``). Conditions are compared after normalizing GitHub's
    documented ref tokens; unknown tokens and malformed security state fail closed as drift.
    """
    try:
        return security_payload(desired, default_branch=default_branch) != security_payload(
            live, default_branch=default_branch
        )
    except ValueError:
        return True


def drifted_ruleset_names(desired_payloads: list[dict[str, Any]], live_payloads: list[dict[str, Any]]) -> list[str]:
    """Names of desired rulesets MISSING from, or content-DRIFTED on, the live platform (§5.6).

    R3-10: matched by ``(name, target)`` — a live ruleset that shares a name but targets a different
    ref kind (e.g. a tag ruleset named like the branch one) is NOT the desired branch ruleset, so it
    must not satisfy presence/content while real branch protection is absent."""
    live_by_key: dict[tuple[object, object], dict[str, Any]] = {}
    for payload in live_payloads:
        if not isinstance(payload, dict) or not isinstance(payload.get("name"), str) or not payload["name"]:
            raise ValueError("live ruleset payload is missing a non-empty string 'name'")
        key = (payload["name"], payload.get("target"))
        if key in live_by_key:
            raise ValueError(f"duplicate live ruleset identity {key!r}")
        live_by_key[key] = payload
    drifted: list[str] = []
    for desired in desired_payloads:
        name = desired.get("name")
        if not isinstance(name, str) or not name:
            # R9-18 (§5.14): a desired ruleset without a string `name` has no identity, so it could
            # never be matched and its absence would read CLEAN. That is a library-data error — fail
            # loud (run `aviato validate`), never silently drop a required ruleset from drift.
            raise ValueError("desired ruleset payload is missing a non-empty string 'name'")
        live = live_by_key.get((name, desired.get("target")))
        if live is None or ruleset_content_drift(desired, live):
            drifted.append(name)
    return drifted


def render_all_rulesets(
    *,
    root: Path,
    required_approvals: int | None = None,
    extra_status_checks: list[str] | None = None,
) -> list[dict[str, Any]]:
    policy = load_policy(root=root)
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
    root: Path | None = None,
    payloads: list[dict[str, Any]] | None = None,
    apply: bool,
    required_approvals: int | None = None,
    extra_status_checks: list[str] | None = None,
) -> Iterator[RulesetApplyResult]:
    """Yield a confirmation per upserted ruleset (R2-4-6).

    Returns a GENERATOR that yields each upsert's message as it succeeds, so the caller prints it
    BEFORE a later-repo/later-ruleset failure aborts — otherwise a multi-repo apply that fails on
    repo N would surface only the error, with no record that repos 1..N-1 were already mutated.

    R3-1-GENLAZY: ``render_all_rulesets`` is run EAGERLY here (at call time), not deferred to first
    advance — so a malformed-library-data ``ValueError`` surfaces when ``apply_rulesets`` is called,
    matching the old eager-list semantics, regardless of whether/how the caller consumes the
    generator. Only the per-upsert platform writes are streamed lazily.
    """
    if payloads is None:
        if root is None:
            raise ValueError("apply_rulesets requires an explicit snapshot policy root or pre-rendered payloads")
        payloads = render_all_rulesets(
            root=root,
            required_approvals=required_approvals,
            extra_status_checks=extra_status_checks,
        )

    def _stream() -> Iterator[RulesetApplyResult]:
        for slug in slugs:
            for payload in payloads:
                yield github.upsert_ruleset(slug, payload, apply=apply)

    return _stream()
