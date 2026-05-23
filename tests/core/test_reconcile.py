from __future__ import annotations

from aviato.core.consent import ACTOR_HUMAN, ROLE_PRIVILEGED
from aviato.core.reconcile import ReconcileState, reconcile_decision
from aviato.core.settingsdrift import classify_settings, diff_identity

# The gate binds to the APPLY-TIME recomputed diff (§2.8/§6.4), so the consent and
# confirmation ids must equal the real identity of the default desired/live diff.
_DEFAULT_DIFF_ID = diff_identity(classify_settings(desired={"required_reviews": 2}, live={"required_reviews": 1}))


def _state(**overrides) -> ReconcileState:
    base = dict(
        issue_open=True,
        consent_present=True,
        consent_diff_id=_DEFAULT_DIFF_ID,
        current_diff_id=_DEFAULT_DIFF_ID,
        actor_type=ACTOR_HUMAN,
        role=ROLE_PRIVILEGED,
        role_lookup_ok=True,
        issue_edited_by_nonhuman_since_grant=False,
        confirmed_diff_id=_DEFAULT_DIFF_ID,  # matches the recomputed diff id
        desired_settings={"required_reviews": 2},
        live_settings={"required_reviews": 1},
        tool_version="1.0.0",
        pin="v1",
        recorded_version="1.0.0",
    )
    base.update(overrides)
    return ReconcileState(**base)


def test_gate_binds_to_recomputed_diff_id_not_state_field() -> None:
    # Hardening: the consent/confirmation gate must bind to the diff RECOMPUTED at apply
    # time, not a caller-supplied current_diff_id field that could diverge from it. Here
    # the state field is stale/wrong but consent+confirmation match the real recomputed
    # diff → the reconcile still applies.
    outcome = reconcile_decision(
        _state(
            consent_diff_id=_DEFAULT_DIFF_ID,
            confirmed_diff_id=_DEFAULT_DIFF_ID,
            current_diff_id="STALE-WRONG-VALUE",
        )
    )
    assert outcome.action == "apply"


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
    assert reconcile_decision(_state(confirmed_diff_id=None)).action == "abort"


def test_stale_confirmation_aborts() -> None:
    # #2: the operator confirmed an id that no longer matches the apply-time diff
    # (live state changed since review) -> abort, never apply a different diff (§2.8).
    outcome = reconcile_decision(_state(confirmed_diff_id="OLDID", current_diff_id="abc"))
    assert outcome.action == "abort"
    assert "no longer matches" in outcome.reason


def test_version_mismatch_refused() -> None:
    # tool below the recorded marker version → incompatible (§2.6)
    assert reconcile_decision(_state(tool_version="1.0.0", recorded_version="1.5.0")).action == "refuse"


def test_major_mismatch_refused() -> None:
    assert reconcile_decision(_state(tool_version="2.0.0", pin="v1", recorded_version="1.0.0")).action == "refuse"


def test_version_mismatch_message_names_the_override_flag() -> None:
    # #5: the refusal must name the actual flag (--override-version-pin), not just "override required".
    outcome = reconcile_decision(_state(tool_version="1.0.0", recorded_version="1.5.0"))
    assert outcome.action == "refuse"
    assert "--override-version-pin" in outcome.reason


def test_version_mismatch_applies_with_override() -> None:
    # #5: the advertised override actually exists and lets a confirmed, consented,
    # admin-granted reconcile proceed despite the pin mismatch.
    outcome = reconcile_decision(_state(tool_version="1.0.0", recorded_version="1.5.0", override_version_pin=True))
    assert outcome.action == "apply"
    assert "overridden" in outcome.reason


def test_unparseable_recorded_version_refuses_not_crashes() -> None:
    # A corrupted/empty marker yields an unparseable recorded version. is_compatible would
    # raise CompatibilityError; the decision must fail CLOSED to the operator-gated "refuse"
    # (so the §5.7 issue-audit path runs), not crash out of the pure decision (§2.6/§2.7).
    outcome = reconcile_decision(_state(recorded_version=""))
    assert outcome.action == "refuse"
    assert "--override-version-pin" in outcome.reason


def test_unparseable_recorded_version_applies_with_override() -> None:
    outcome = reconcile_decision(_state(recorded_version="", override_version_pin=True))
    assert outcome.action == "apply"
