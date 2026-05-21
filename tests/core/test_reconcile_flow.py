from __future__ import annotations

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
        operator_confirmed=True,
    )
    assert outcome.action == "apply"
    names = platform.call_names()
    assert "apply_settings" in names
    assert "comment_issue" in names
    assert platform.settings["required_reviews"] == 2


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
        operator_confirmed=True,
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
        operator_confirmed=True,
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
        operator_confirmed=True,
    )
    assert outcome.action == "refuse"
    assert "apply_settings" not in platform.call_names()
