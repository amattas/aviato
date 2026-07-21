from __future__ import annotations

import contextlib
import dataclasses
import sys
from typing import Any

from .errors import CompatibilityError
from .ports import Platform
from .reconcile import (
    DeclarativeReconcileOutcome,
    ReconcileOutcome,
    ReconcilePlan,
    ReconcileState,
    build_reconcile_plan,
    reconcile_decision,
)
from .settings_drift_flow import diff_identity
from .settingsdrift import classify_settings
from .version import is_compatible


def plan_reconcile(
    platform: Platform,
    *,
    repo: str,
    desired_settings: dict[str, Any],
    pin: str,
    tool_version: str,
    recorded_version: str,
) -> ReconcilePlan:
    return build_reconcile_plan(
        desired_settings=desired_settings,
        live_settings=platform.read_settings(repo),
        pin=pin,
        tool_version=tool_version,
        recorded_version=recorded_version,
    )


def execute_reconcile(
    platform: Platform,
    *,
    repo: str,
    plan: ReconcilePlan,
    override_version_pin: bool = False,
) -> DeclarativeReconcileOutcome:
    if plan.clean:
        return DeclarativeReconcileOutcome("noop", "settings already match")

    try:
        compatible = is_compatible(
            tool=plan.tool_version,
            pinned=plan.pin,
            recorded=plan.recorded_version,
        )
    except CompatibilityError:
        compatible = False

    if not compatible and not override_version_pin:
        return DeclarativeReconcileOutcome(
            "refuse",
            "tool version does not satisfy the recorded compatibility contract",
        )

    final_live = platform.read_settings(repo)
    final_plan = build_reconcile_plan(
        desired_settings=plan.desired_settings,
        live_settings=final_live,
        pin=plan.pin,
        tool_version=plan.tool_version,
        recorded_version=plan.recorded_version,
    )
    if final_plan.diff_id != plan.diff_id:
        return DeclarativeReconcileOutcome(
            "abort",
            "live settings changed after the plan was displayed; rerun reconcile",
        )

    result = platform.apply_settings(
        repo,
        plan.desired_settings,
        expected_live=final_live,
    )
    if result.skipped:
        return DeclarativeReconcileOutcome(
            "degraded",
            "supported settings were applied but some fields were skipped",
            skipped=result.skipped,
            notes=result.notes,
        )
    return DeclarativeReconcileOutcome(
        "apply",
        "current declaration applied",
        notes=result.notes,
    )


def run_reconcile(
    platform: Platform,
    *,
    repo: str,
    issue_key: str,
    desired_settings: dict[str, Any],
    pin: str,
    tool_version: str,
    recorded_version: str,
    confirmed_diff_id: str | None,
    override_version_pin: bool = False,
) -> ReconcileOutcome:
    """Operator-gated settings reconcile against a tracking issue (§5.7).

    Re-reads live state and the issue/consent channel at apply time (§2.8),
    builds the :class:`ReconcileState`, and delegates the decision to
    :func:`reconcile_decision`. Only on an ``apply`` decision does it call the
    single mutating method (``apply_settings``); every outcome is commented on the
    issue, which is left open for audit. The returned outcome always carries the
    apply-time recomputed diff (id + per-key values) so the caller can show the
    operator exactly what was applied — or why it aborted (§2.8).
    """
    issue = platform.get_issue(repo, issue_key)
    if issue is None or not issue.open:
        return ReconcileOutcome("refuse", "issue is missing or closed; reopen to act")

    live = platform.read_settings(repo)
    diff = classify_settings(desired=desired_settings, live=live)
    current_diff_id = diff_identity(diff)

    def _state(issue_obj: Any, diff_id: str, live_settings: dict[str, Any]) -> ReconcileState:
        # Build the decision input from a (possibly re-read) issue + diff. Version-pin / confirmed-id
        # inputs are constant across reads; only the consent channel and the live diff can change.
        return ReconcileState(
            issue_open=issue_obj.open,
            consent_present=issue_obj.consent_diff_id is not None,
            consent_diff_id=issue_obj.consent_diff_id,
            current_diff_id=diff_id,
            actor_type=issue_obj.consent_actor_type,
            role=issue_obj.consent_role,
            role_lookup_ok=issue_obj.consent_role_lookup_ok,
            issue_edited_by_nonhuman_since_grant=issue_obj.edited_by_nonhuman_since_grant,
            confirmed_diff_id=confirmed_diff_id,
            desired_settings=desired_settings,
            live_settings=live_settings,
            tool_version=tool_version,
            pin=pin,
            recorded_version=recorded_version,
            override_version_pin=override_version_pin,
            issue_ambiguous=issue_obj.ambiguous,
        )

    state = _state(issue, current_diff_id, live)
    outcome = reconcile_decision(state)
    # R2-6/§5.7: a non-human edit since the grant VOIDS consent — actually revoke the grant label
    # (not just comment), so a subsequent run doesn't re-evaluate a stale grant. The decision
    # reports this as an abort with "consent voided"; effect it here on the platform.
    if state.issue_edited_by_nonhuman_since_grant and issue.consent_diff_id is not None:
        with contextlib.suppress(Exception):
            platform.revoke_consent(repo, issue_key, issue.consent_diff_id)
    # Surface the apply-time recomputed diff on every outcome (§2.8): the caller renders
    # it so the operator confirms/sees the SAME read that was applied, not the preview.
    outcome = dataclasses.replace(
        outcome, diff_id=current_diff_id, changes=dict(diff.changes), values=dict(diff.values)
    )

    if outcome.action == "apply":
        # C12-R3-1 (§5.7/§2.8): RE-READ the consent channel + live settings IMMEDIATELY before the
        # privileged write and re-authorize against the RECOMPUTED diff. The entry-time decision can be
        # stale — a consent label revoked, the issue closed, or the live settings/diff changed between
        # the entry read and here must ABORT, never apply on stale authorization. (The docstring's
        # apply-time re-read promise was previously unfulfilled.)
        fresh_issue = platform.get_issue(repo, issue_key)
        if fresh_issue is None or not fresh_issue.open:
            return dataclasses.replace(
                ReconcileOutcome("refuse", "tracking issue became missing/closed before apply; re-run"),
                diff_id=current_diff_id,
                changes=dict(diff.changes),
                values=dict(diff.values),
            )
        live = platform.read_settings(repo)
        diff = classify_settings(desired=desired_settings, live=live)
        current_diff_id = diff_identity(diff)
        recheck = reconcile_decision(_state(fresh_issue, current_diff_id, live))
        if recheck.action != "apply":
            with contextlib.suppress(Exception):
                platform.comment_issue(
                    repo, issue_key, f"Apply ABORTED — consent/state changed before apply: {recheck.reason}"
                )
            return dataclasses.replace(
                recheck, diff_id=current_diff_id, changes=dict(diff.changes), values=dict(diff.values)
            )
        # Re-authorized on the fresh read: carry the recomputed diff into the apply + audit below.
        outcome = dataclasses.replace(
            recheck, diff_id=current_diff_id, changes=dict(diff.changes), values=dict(diff.values)
        )
        # Apply the full DESIRED state, not the diff. The platform binding constructs
        # the purpose-built write payload(s) from this (§2.9): branch protection is a
        # wholesale PUT whose accepted payload is the complete protection object, so a
        # diff-only payload would DROP the unchanged protections. ``outcome.payload``
        # (the changed keys) is recorded in the comment so the operator sees exactly
        # what changed; unchanged desired fields equal live, so applying the full
        # desired state is equivalent to applying just the diff.
        try:
            # Pass the decision-time live snapshot so the binding can fail closed if the modeled
            # branch state drifted since the diff/consent were computed (§2.8/§5.7, review #14).
            apply_result = platform.apply_settings(repo, desired_settings, expected_live=live)
        except Exception as exc:
            # §5.7 audit: an apply that throws mid-flight may have PARTIALLY landed, so it
            # must leave a record on the issue, then propagate (fail-closed) — never vanish
            # with no breadcrumb. A best-effort comment must not mask the original error.
            with contextlib.suppress(Exception):
                platform.comment_issue(repo, issue_key, f"Apply FAILED for diff {current_diff_id}: {exc}")
            raise
        # Audit comment reports the COMPLETE recomputed change set (additive + destructive
        # removals), not the additive-only write subset (outcome.payload) — a removed key is
        # the most sensitive change and must appear in the audit trail (§5.7).
        audit = f"Applied diff {current_diff_id} (changes: {outcome.changes})"
        # The binding returns two STRUCTURALLY DISTINCT channels (§5.7): ``skipped`` — desired toggles
        # surfaced-and-SKIPPED because a §17 feature was unavailable — and ``notes`` — free-text notes
        # about extra mutations it performed outside the diff (e.g. clearing stale classic PR-review
        # protection a ruleset now owns). They are labeled by channel, never by a lossy string heuristic
        # (which mislabeled API-keyed skip names as mutation notes and vice versa).
        # R5-4: if the binding surfaced-and-skipped a §17 toggle (feature unavailable), the audit
        # must say so rather than overstate a clean apply — the operator needs to know a requested
        # security setting did NOT land (enable it per §17, then re-reconcile).
        if apply_result.skipped:
            audit += f"; SKIPPED unavailable: {sorted(apply_result.skipped)}"
        # An extra mutation (e.g. a cleared conflicting classic PR-review block) is the most sensitive
        # kind of change — it must appear verbatim in the §5.7 audit trail, never be dropped.
        for note in sorted(apply_result.notes):
            audit += f"; {note}"
    else:
        audit = f"{outcome.action}: {outcome.reason}"

    # The audit comment is a best-effort breadcrumb (§5.7), never the operation itself. On the
    # apply path the privileged change has ALREADY landed, so a transient failure POSTING the
    # comment must not raise out and make the operator think the apply failed (and re-run it);
    # on a non-apply path nothing mutated. Either way, warn loudly but still return the outcome.
    try:
        platform.comment_issue(repo, issue_key, audit)
    except Exception as exc:  # noqa: BLE001 - audit comment is best-effort, never the operation
        print(
            f"WARNING: {repo} reconcile outcome '{outcome.action}' (diff {current_diff_id}) could "
            f"not be recorded on the issue: {exc}. The decision still stands (apply, if any, landed).",
            file=sys.stderr,
        )

    return outcome
