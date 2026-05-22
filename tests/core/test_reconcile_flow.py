from __future__ import annotations

import pytest

from aviato.core.ports import Issue
from aviato.core.reconcile_flow import run_reconcile
from aviato.core.settings_drift_flow import diff_identity
from aviato.core.settingsdrift import classify_settings

from .fakeplatform import FakePlatform


def _current_diff_id(desired, live) -> str:
    return diff_identity(classify_settings(desired=desired, live=live))


def test_apply_path_mutates_and_comments() -> None:
    desired = {"required_reviews": 2}
    live = {"required_reviews": 1}
    diff_id = _current_diff_id(desired, live)
    issue = Issue(
        key="k",
        open=True,
        consent_diff_id=diff_id,
        consent_actor_type="User",
        consent_role="admin",
        consent_role_lookup_ok=True,
    )
    platform = FakePlatform(settings=dict(live), issues={"k": issue})
    outcome = run_reconcile(
        platform,
        repo="o/r",
        issue_key="k",
        desired_settings=desired,
        pin="v1",
        tool_version="1.0.0",
        recorded_version="1.0.0",
        confirmed_diff_id=diff_id,
    )
    assert outcome.action == "apply"
    names = platform.call_names()
    assert "apply_settings" in names
    assert "comment_issue" in names
    assert platform.settings["required_reviews"] == 2


def test_apply_succeeds_even_if_audit_comment_fails(capsys) -> None:
    # §5.7 audit breadcrumb is best-effort: once apply_settings has landed, a transient failure
    # posting the "Applied" comment must NOT raise out (which would make the operator think the
    # privileged change failed and re-run it). The apply outcome is still returned; a warning is
    # emitted so the missing breadcrumb is visible.
    desired = {"required_reviews": 2}
    live = {"required_reviews": 1}
    diff_id = _current_diff_id(desired, live)
    issue = Issue(
        key="k",
        open=True,
        consent_diff_id=diff_id,
        consent_actor_type="User",
        consent_role="admin",
        consent_role_lookup_ok=True,
    )
    platform = FakePlatform(settings=dict(live), issues={"k": issue}, fail_comment=True)
    outcome = run_reconcile(
        platform,
        repo="o/r",
        issue_key="k",
        desired_settings=desired,
        pin="v1",
        tool_version="1.0.0",
        recorded_version="1.0.0",
        confirmed_diff_id=diff_id,
    )
    assert outcome.action == "apply"  # did not raise; outcome returned
    assert platform.settings["required_reviews"] == 2  # apply landed
    assert "could not be recorded" in capsys.readouterr().err


def test_apply_passes_full_desired_state_to_binding() -> None:
    # §2.9 contract: the flow hands the binding the FULL desired state — the binding
    # builds the purpose-built write payload(s) from it. Branch protection is a
    # wholesale PUT whose accepted payload is the complete protection object, so the
    # flow must NOT pre-trim to the diff (that would drop unchanged protections). The
    # changed-keys view lives on outcome.payload (recorded for the operator), not the write.
    desired = {"required_reviews": 2, "requires_pull_request": True, "required_status_checks": ["verify"]}
    live = {"required_reviews": 1, "requires_pull_request": True, "required_status_checks": ["verify"]}
    diff_id = _current_diff_id(desired, live)
    issue = Issue(
        key="k",
        open=True,
        consent_diff_id=diff_id,
        consent_actor_type="User",
        consent_role="admin",
        consent_role_lookup_ok=True,
    )
    platform = FakePlatform(settings=dict(live), issues={"k": issue})
    outcome = run_reconcile(
        platform,
        repo="o/r",
        issue_key="k",
        desired_settings=desired,
        pin="1",
        tool_version="1.0.0",
        recorded_version="1.0.0",
        confirmed_diff_id=diff_id,
    )
    assert outcome.action == "apply"
    applied = [args[1] for name, args in platform.calls if name == "apply_settings"]
    assert applied == [desired]
    # The operator-facing record still shows only what changed.
    assert outcome.payload == {"required_reviews": 2}


def test_apply_audit_comment_includes_destructive_removals() -> None:
    # §5.7: the audit comment must reflect the COMPLETE recomputed change set, including
    # keys present in live but removed from desired (destructive). The additive-only write
    # subset (outcome.payload) omits removals, leaving an incomplete audit trail for the
    # most security-sensitive class of change.
    desired = {"required_reviews": 2}
    live = {"required_reviews": 1, "legacy_restriction": True}
    diff_id = _current_diff_id(desired, live)
    issue = Issue(
        key="k",
        open=True,
        consent_diff_id=diff_id,
        consent_actor_type="User",
        consent_role="admin",
        consent_role_lookup_ok=True,
    )
    platform = FakePlatform(settings=dict(live), issues={"k": issue})
    outcome = run_reconcile(
        platform,
        repo="o/r",
        issue_key="k",
        desired_settings=desired,
        pin="v1",
        tool_version="1.0.0",
        recorded_version="1.0.0",
        confirmed_diff_id=diff_id,
    )
    assert outcome.action == "apply"
    comments = [args[2] for name, args in platform.calls if name == "comment_issue"]
    assert any("legacy_restriction" in body for body in comments), comments


def test_apply_failure_is_recorded_on_issue_then_reraised() -> None:
    # §5.7: an apply that throws mid-flight must still leave an audit record on the issue
    # (the apply may have partially landed) and then propagate — never silently vanish with
    # no breadcrumb. The mutation is the most sensitive op; its failure must be traceable.
    desired = {"required_reviews": 2}
    live = {"required_reviews": 1}
    diff_id = _current_diff_id(desired, live)
    issue = Issue(
        key="k",
        open=True,
        consent_diff_id=diff_id,
        consent_actor_type="User",
        consent_role="admin",
        consent_role_lookup_ok=True,
    )
    platform = FakePlatform(settings=dict(live), issues={"k": issue}, fail_apply=True)
    with pytest.raises(RuntimeError):
        run_reconcile(
            platform,
            repo="o/r",
            issue_key="k",
            desired_settings=desired,
            pin="1",
            tool_version="1.0.0",
            recorded_version="1.0.0",
            confirmed_diff_id=diff_id,
        )
    comments = [args[2] for name, args in platform.calls if name == "comment_issue"]
    assert any("fail" in body.lower() for body in comments), comments


def test_missing_issue_refused() -> None:
    platform = FakePlatform(settings={"required_reviews": 1})
    outcome = run_reconcile(
        platform,
        repo="o/r",
        issue_key="missing",
        desired_settings={"required_reviews": 2},
        pin="v1",
        tool_version="1.0.0",
        recorded_version="1.0.0",
        confirmed_diff_id="anything",
    )
    assert outcome.action == "refuse"
    assert "apply_settings" not in platform.call_names()


def test_empty_diff_noop_does_not_mutate() -> None:
    # consent bound to the (now-empty) recomputed diff; the change converged externally
    empty_id = _current_diff_id({"x": 1}, {"x": 1})
    issue = Issue(
        key="k",
        open=True,
        consent_diff_id=empty_id,
        consent_actor_type="User",
        consent_role="admin",
        consent_role_lookup_ok=True,
    )
    platform = FakePlatform(settings={"x": 1}, issues={"k": issue})
    outcome = run_reconcile(
        platform,
        repo="o/r",
        issue_key="k",
        desired_settings={"x": 1},
        pin="v1",
        tool_version="1.0.0",
        recorded_version="1.0.0",
        confirmed_diff_id=empty_id,
    )
    assert outcome.action == "noop"
    assert "apply_settings" not in platform.call_names()


def test_non_human_consent_refused_no_mutation() -> None:
    desired = {"required_reviews": 2}
    live = {"required_reviews": 1}
    issue = Issue(
        key="k",
        open=True,
        consent_diff_id=_current_diff_id(desired, live),
        consent_actor_type="Bot",
        consent_role="admin",
        consent_role_lookup_ok=True,
    )
    platform = FakePlatform(settings=dict(live), issues={"k": issue})
    outcome = run_reconcile(
        platform,
        repo="o/r",
        issue_key="k",
        desired_settings=desired,
        pin="v1",
        tool_version="1.0.0",
        recorded_version="1.0.0",
        confirmed_diff_id=_current_diff_id(desired, live),
    )
    assert outcome.action == "refuse"
    assert "apply_settings" not in platform.call_names()
