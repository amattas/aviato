from __future__ import annotations

from aviato.core.reconcile import ReconcileState, reconcile_decision


def _state(**overrides) -> ReconcileState:
    base = dict(
        issue_open=True,
        consent_present=True,
        consent_diff_id="abc",
        current_diff_id="abc",
        actor_type="User",
        role="admin",
        role_lookup_ok=True,
        issue_edited_by_nonhuman_since_grant=False,
        operator_confirmed=True,
        desired_settings={"required_reviews": 2},
        live_settings={"required_reviews": 1},
        tool_version="1.0.0",
        pin="v1",
        recorded_version="1.0.0",
    )
    base.update(overrides)
    return ReconcileState(**base)


def test_apply_on_full_valid_path() -> None:
    outcome = reconcile_decision(_state())
    assert outcome.action == "apply"
    assert outcome.payload == {"required_reviews": 2}  # purpose-built from recomputed diff


def test_closed_issue_refused() -> None:
    assert reconcile_decision(_state(issue_open=False)).action == "refuse"


def test_absent_consent_refused() -> None:
    assert reconcile_decision(_state(consent_present=False)).action == "refuse"


def test_stale_consent_refused() -> None:
    assert reconcile_decision(_state(consent_diff_id="OLD")).action == "refuse"


def test_non_human_granter_fails_closed() -> None:
    assert reconcile_decision(_state(actor_type="Bot")).action == "refuse"


def test_non_admin_fails_closed() -> None:
    assert reconcile_decision(_state(role="write")).action == "refuse"


def test_empty_recomputed_diff_is_noop() -> None:
    outcome = reconcile_decision(_state(desired_settings={"x": 1}, live_settings={"x": 1}))
    assert outcome.action == "noop"


def test_empty_diff_noops_even_with_stale_consent() -> None:
    # external convergence: nothing left to apply → no-op regardless of stale consent (§2.8)
    outcome = reconcile_decision(
        _state(
            desired_settings={"x": 1},
            live_settings={"x": 1},
            consent_diff_id="STALE",
            current_diff_id="NEW",
        )
    )
    assert outcome.action == "noop"


def test_issue_edited_by_nonhuman_aborts() -> None:
    assert reconcile_decision(_state(issue_edited_by_nonhuman_since_grant=True)).action == "abort"


def test_operator_declines_recomputed_diff_aborts() -> None:
    assert reconcile_decision(_state(operator_confirmed=False)).action == "abort"


def test_version_mismatch_refused() -> None:
    # tool below the recorded marker version → incompatible (§2.6)
    assert reconcile_decision(_state(tool_version="1.0.0", recorded_version="1.5.0")).action == "refuse"


def test_major_mismatch_refused() -> None:
    assert reconcile_decision(_state(tool_version="2.0.0", pin="v1", recorded_version="1.0.0")).action == "refuse"
