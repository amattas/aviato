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
    # §8.3: the stale grant must be actually REVOKED (label removed), not merely commented —
    # otherwise drift oscillating back to the old diff id would re-authorize on the stale label.
    assert "revoke_consent" in platform.call_names()
    assert "comment_issue" in platform.call_names()
    revoke = next(args for name, args in platform.calls if name == "revoke_consent")
    assert revoke == ("o/r", "k", "STALE")


def test_consent_oscillation_back_to_old_diff_requires_fresh_consent() -> None:
    # §8.3/§6.4: after drift changes away from a consented diff and the consent is voided,
    # the in-memory issue carries no consent — so even if drift later returns to the original
    # diff, get_issue reports no active consent and reconcile would need a fresh grant.
    platform = FakePlatform(
        settings={"required_reviews": 1},
        issues={"k": Issue(key="k", open=True, consent_diff_id="STALE")},
    )
    run_settings_drift(platform, repo="o/r", desired_settings={"required_reviews": 2}, issue_key="k")
    issue = platform.get_issue("o/r", "k")
    assert issue is not None and issue.consent_diff_id is None


def test_drifted_ruleset_is_reported_even_with_clean_settings() -> None:
    # §5.6: a ruleset that is missing OR content-drifted (computed by the caller) must be reported
    # (not "clean"), remediated via apply-rulesets WITH --profile — even when settings match.
    platform = FakePlatform(settings={"required_reviews": 2})
    outcome = run_settings_drift(
        platform,
        repo="o/r",
        desired_settings={"required_reviews": 2},  # no settings drift
        issue_key="k",
        drifted_rulesets=("Common: release tag format",),
        profile="python-library",
    )
    assert outcome.status == "reported"
    assert outcome.drifted_rulesets == ("Common: release tag format",)
    assert outcome.diff_id is None  # no settings diff → no consent-bound id
    _, args = next(c for c in platform.calls if c[0] == "open_or_update_issue")
    body = args[3]
    assert "apply-rulesets o/r --apply --profile python-library" in body  # M-2: --profile included
    assert "Common: release tag format" in body


def test_no_drifted_rulesets_with_clean_settings_is_clean() -> None:
    platform = FakePlatform(settings={"required_reviews": 2})
    outcome = run_settings_drift(
        platform,
        repo="o/r",
        desired_settings={"required_reviews": 2},
        issue_key="k",
        drifted_rulesets=(),
        profile="python-library",
    )
    assert outcome.status == "clean"
    assert outcome.drifted_rulesets == ()


def test_resolved_empty_diff_voids_stale_consent() -> None:
    # §5.6/§8.3: when a previously-consented diff RESOLVES to empty, the stale consent must be
    # VOIDED — not left to re-authorize if the same diff later reappears (the A→∅→A oscillation).
    platform = FakePlatform(
        settings={"required_reviews": 2},  # live already matches desired → empty diff
        issues={"k": Issue(key="k", open=True, consent_diff_id="STALE")},
    )
    outcome = run_settings_drift(platform, repo="o/r", desired_settings={"required_reviews": 2}, issue_key="k")
    assert outcome.status == "resolved"
    assert outcome.consent_voided is True
    assert "revoke_consent" in platform.call_names()
    # And the in-memory issue now carries no consent → a reappearance needs fresh consent.
    issue = platform.get_issue("o/r", "k")
    assert issue is not None and issue.consent_diff_id is None


def test_resolved_empty_diff_without_consent_does_not_revoke() -> None:
    # No stale consent → resolved comment only, no revoke (no false void).
    platform = FakePlatform(
        settings={"required_reviews": 2},
        issues={"k": Issue(key="k", open=True)},
    )
    outcome = run_settings_drift(platform, repo="o/r", desired_settings={"required_reviews": 2}, issue_key="k")
    assert outcome.status == "resolved"
    assert outcome.consent_voided is False
    assert "revoke_consent" not in platform.call_names()


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
