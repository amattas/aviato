from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .consent import authorize
from .settingsdrift import classify_settings
from .version import is_compatible

Action = Literal["apply", "noop", "abort", "refuse"]


@dataclass(frozen=True)
class ReconcileState:
    """The state gathered at apply time for a settings reconcile (§5.7).

    A thin platform adapter (around ``gh``) populates this from the live issue,
    its consent record, and live settings; the decision logic below is pure so
    it can be exhaustively tested. ``current_diff_id`` and ``*_settings`` are the
    apply-time **recomputed** values, never an earlier snapshot (§2.8).
    """

    issue_open: bool
    consent_present: bool
    consent_diff_id: str | None
    current_diff_id: str
    actor_type: str | None
    role: str | None
    role_lookup_ok: bool
    issue_edited_by_nonhuman_since_grant: bool
    # The diff id the operator explicitly confirmed (CLI --confirm <id>), bound to the
    # exact content they reviewed. The apply only proceeds if it equals the apply-time
    # recomputed current_diff_id — so a change to the live state after review aborts
    # rather than silently applying a different diff (§2.8/§5.7).
    confirmed_diff_id: str | None
    desired_settings: dict[str, Any]
    live_settings: dict[str, Any]
    tool_version: str
    pin: str
    recorded_version: str
    # Operator escape hatch for the §2.6 version-pin gate (the "override required"
    # path). Default False keeps the gate fail-closed.
    override_version_pin: bool = False


@dataclass(frozen=True)
class ReconcileOutcome:
    action: Action
    reason: str
    payload: dict[str, Any] | None = None
    # The apply-time recomputed diff, surfaced so the operator sees the exact change
    # that was (or would be) applied — not just the earlier preview (§2.8).
    diff_id: str | None = None
    changes: dict[str, str] | None = None
    values: dict[str, dict[str, Any]] | None = None


def _purpose_built_payload(desired: dict[str, Any], live: dict[str, Any], diff_keys) -> dict[str, Any]:
    """Construct a write payload of only the changed fields (§2.9): no read-shaped replay."""
    return {key: desired[key] for key in diff_keys if key in desired}


def reconcile_decision(state: ReconcileState) -> ReconcileOutcome:
    """Decide the outcome of an operator-gated settings reconcile (§5.7, §5.8, §2.8).

    Order mirrors the §5.7 flowchart: refuse on a closed issue or absent/stale
    consent; fail-closed authorize the granter; recompute the diff at apply time
    (empty → no-op); abort if the issue/consent was edited by a non-human since
    the grant, or if the operator declines the recomputed diff; refuse on a
    version-pin mismatch; otherwise apply a purpose-built payload.
    """
    if not state.issue_open:
        return ReconcileOutcome("refuse", "issue is closed; reopen to act")

    # Apply-time recompute first (§2.8): if the change already converged externally
    # the recomputed diff is empty, so no-op regardless of consent state — there is
    # nothing to authorize, and refusing on stale consent would be wrong.
    diff = classify_settings(desired=state.desired_settings, live=state.live_settings)
    if not diff.changes:
        return ReconcileOutcome("noop", "recomputed diff is empty; already converged")

    if not state.consent_present or state.consent_diff_id != state.current_diff_id:
        return ReconcileOutcome("refuse", "consent absent or not bound to the current diff; needs (re-)consent")

    decision = authorize(
        actor_type=state.actor_type,
        consent_diff_id=state.consent_diff_id,
        current_diff_id=state.current_diff_id,
        role_lookup_ok=state.role_lookup_ok,
        role=state.role,
    )
    if not decision.allowed:
        return ReconcileOutcome("refuse", f"authorization denied: {decision.reason}")

    if state.issue_edited_by_nonhuman_since_grant:
        return ReconcileOutcome("abort", "issue/consent edited by a non-human since the grant; consent voided")

    if state.confirmed_diff_id is None:
        return ReconcileOutcome(
            "abort", f"operator did not confirm the apply-time diff; re-run with --confirm {state.current_diff_id}"
        )
    if state.confirmed_diff_id != state.current_diff_id:
        return ReconcileOutcome(
            "abort",
            f"confirmed diff {state.confirmed_diff_id} no longer matches the apply-time diff "
            f"{state.current_diff_id} (live state changed since review); re-review and re-confirm",
        )

    pin_overridden = False
    if not is_compatible(tool=state.tool_version, pinned=state.pin, recorded=state.recorded_version):
        if not state.override_version_pin:
            return ReconcileOutcome(
                "refuse", "version-pin mismatch (§2.6); re-run with --override-version-pin to proceed"
            )
        pin_overridden = True

    payload = _purpose_built_payload(state.desired_settings, state.live_settings, diff.changes)
    reason = "human consent, admin role, confirmed recomputed diff"
    if pin_overridden:
        reason += " (version-pin mismatch overridden by operator, §2.6)"
    return ReconcileOutcome("apply", reason, payload=payload)
