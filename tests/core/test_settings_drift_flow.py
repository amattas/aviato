from __future__ import annotations

import pytest

from aviato.core.ports import Issue
from aviato.core.settings_drift_flow import run_settings_drift

from .fakeplatform import FakePlatform


def test_non_empty_diff_opens_issue_with_reconcile_command() -> None:
    platform = FakePlatform(settings={"required_reviews": 1})
    outcome = run_settings_drift(
        platform, repo="o/r", desired_settings={"required_reviews": 2}, issue_key="aviato-settings"
    )
    assert outcome.status == "reported"
    assert "open_or_update_issue" in platform.call_names()
    _, args = next(c for c in platform.calls if c[0] == "open_or_update_issue")
    body = args[3]
    assert "reconcile" in body.lower()


def test_destructive_change_is_flagged() -> None:
    platform = FakePlatform(settings={"required_reviews": 2})
    outcome = run_settings_drift(platform, repo="o/r", desired_settings={"required_reviews": 1}, issue_key="k")
    assert outcome.destructive is True


def test_empty_diff_with_open_issue_comments_resolved_never_closes() -> None:
    platform = FakePlatform(settings={"x": 1}, issues={"k": Issue(key="k", open=True)})
    outcome = run_settings_drift(platform, repo="o/r", desired_settings={"x": 1}, issue_key="k")
    assert outcome.status == "resolved"
    names = platform.call_names()
    assert "comment_issue" in names
    assert "apply_settings" not in names  # never mutates


def test_empty_diff_no_issue_is_clean_noop() -> None:
    platform = FakePlatform(settings={"x": 1})
    outcome = run_settings_drift(platform, repo="o/r", desired_settings={"x": 1}, issue_key="k")
    assert outcome.status == "clean"
    assert platform.calls == []


def test_changed_diff_voids_prior_consent() -> None:
    # an existing issue recorded consent for a different diff id
    platform = FakePlatform(
        settings={"required_reviews": 1},
        issues={"k": Issue(key="k", open=True, consent_diff_id="STALE")},
    )
    outcome = run_settings_drift(platform, repo="o/r", desired_settings={"required_reviews": 2}, issue_key="k")
    assert outcome.consent_voided is True
    assert "comment_issue" in platform.call_names()


def test_issue_channel_unavailable_fails_loud() -> None:
    platform = FakePlatform(settings={"required_reviews": 1}, issues_disabled=True)
    with pytest.raises(RuntimeError):
        run_settings_drift(platform, repo="o/r", desired_settings={"required_reviews": 2}, issue_key="k")


def test_flow_never_mutates_settings() -> None:
    platform = FakePlatform(settings={"required_reviews": 1})
    run_settings_drift(platform, repo="o/r", desired_settings={"required_reviews": 2}, issue_key="k")
    assert "apply_settings" not in platform.call_names()


def test_diff_identity_is_bound_to_values_not_just_kind() -> None:
    # #1/§6.4: 1->2 and 1->5 are both "additive" but are DIFFERENT changes, so their
    # consent identities must differ — otherwise consent for 1->2 would authorize 1->5.
    from aviato.core.settings_drift_flow import diff_identity
    from aviato.core.settingsdrift import classify_settings

    id_to_2 = diff_identity(classify_settings(desired={"required_reviews": 2}, live={"required_reviews": 1}))
    id_to_5 = diff_identity(classify_settings(desired={"required_reviews": 5}, live={"required_reviews": 1}))
    assert id_to_2 != id_to_5


def test_diff_identity_fits_consent_label_limit() -> None:
    # §6.4/§5.7 consent binding: the identity is carried as a segment of the consent-grant
    # label a human applies to the tracking issue. GitHub caps label names at 50 chars, so
    # CONSENT_LABEL_PREFIX + diff_id MUST fit — otherwise the label can never be created and
    # the reconcile gate is unreachable. (A regression here once shipped because the only
    # assertion was len == 64; assert the actual round-trip invariant instead.)
    from aviato.core.settings_drift_flow import diff_identity
    from aviato.core.settingsdrift import CONSENT_ID_HEX_LEN, classify_settings
    from aviato.github_platform import CONSENT_LABEL_PREFIX, GITHUB_LABEL_NAME_MAX

    diff_id = diff_identity(classify_settings(desired={"required_reviews": 2}, live={"required_reviews": 1}))
    assert len(diff_id) == CONSENT_ID_HEX_LEN
    assert len(CONSENT_LABEL_PREFIX) + len(diff_id) <= GITHUB_LABEL_NAME_MAX
