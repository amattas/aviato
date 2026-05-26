from __future__ import annotations

import contextlib
import dataclasses
import sys
from typing import Any

from .ports import Platform
from .reconcile import ReconcileOutcome, ReconcileState, reconcile_decision
from .settings_drift_flow import diff_identity
from .settingsdrift import classify_settings


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

    state = ReconcileState(
        issue_open=issue.open,
        consent_present=issue.consent_diff_id is not None,
        consent_diff_id=issue.consent_diff_id,
        current_diff_id=current_diff_id,
        actor_type=issue.consent_actor_type,
        role=issue.consent_role,
        role_lookup_ok=issue.consent_role_lookup_ok,
        issue_edited_by_nonhuman_since_grant=issue.edited_by_nonhuman_since_grant,
        confirmed_diff_id=confirmed_diff_id,
        desired_settings=desired_settings,
        live_settings=live,
        tool_version=tool_version,
        pin=pin,
        recorded_version=recorded_version,
        override_version_pin=override_version_pin,
        issue_ambiguous=issue.ambiguous,
    )

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
            skipped = platform.apply_settings(repo, desired_settings, expected_live=live)
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
        # R5-4: if the binding surfaced-and-skipped a §17 toggle (feature unavailable), the audit
        # must say so rather than overstate a clean apply — the operator needs to know a requested
        # security setting did NOT land (enable it per §17, then re-reconcile).
        if skipped:
            audit += f"; SKIPPED unavailable: {sorted(skipped)}"
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
