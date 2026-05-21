from __future__ import annotations

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
    operator_confirmed: bool,
) -> ReconcileOutcome:
    """Operator-gated settings reconcile against a tracking issue (§5.7).

    Re-reads live state and the issue/consent channel at apply time (§2.8),
    builds the :class:`ReconcileState`, and delegates the decision to
    :func:`reconcile_decision`. Only on an ``apply`` decision does it call the
    single mutating method (``apply_settings``); every outcome is commented on the
    issue, which is left open for audit.
    """
    issue = platform.get_issue(repo, issue_key)
    if issue is None or not issue.open:
        return ReconcileOutcome("refuse", "issue is missing or closed; reopen to act")

    live = platform.read_settings(repo)
    current_diff_id = diff_identity(classify_settings(desired=desired_settings, live=live))

    state = ReconcileState(
        issue_open=issue.open,
        consent_present=issue.consent_diff_id is not None,
        consent_diff_id=issue.consent_diff_id,
        current_diff_id=current_diff_id,
        actor_type=issue.consent_actor_type,
        role=issue.consent_role,
        role_lookup_ok=issue.consent_role_lookup_ok,
        issue_edited_by_nonhuman_since_grant=issue.edited_by_nonhuman_since_grant,
        operator_confirmed=operator_confirmed,
        desired_settings=desired_settings,
        live_settings=live,
        tool_version=tool_version,
        pin=pin,
        recorded_version=recorded_version,
    )

    outcome = reconcile_decision(state)

    if outcome.action == "apply" and outcome.payload is not None:
        platform.apply_settings(repo, outcome.payload)
        platform.comment_issue(repo, issue_key, f"Applied: {outcome.payload}")
    else:
        platform.comment_issue(repo, issue_key, f"{outcome.action}: {outcome.reason}")

    return outcome
