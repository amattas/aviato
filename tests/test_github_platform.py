from __future__ import annotations

import subprocess

import pytest

from aviato import github
from aviato.core.ports import Platform
from aviato.github_platform import (
    GitHubPlatform,
    _label_events,
    current_consent,
    map_branch_settings,
)


def test_current_consent_returns_active_grant() -> None:
    events = [{"action": "labeled", "label": "aviato-consent:abc", "actor_type": "User", "actor_login": "al"}]
    grant = current_consent(events)
    assert grant is not None
    assert grant.diff_id == "abc"
    assert grant.actor_type == "User"
    assert grant.actor_login == "al"


def test_current_consent_revoked_returns_none() -> None:
    events = [
        {"action": "labeled", "label": "aviato-consent:abc", "actor_type": "User", "actor_login": "al"},
        {"action": "unlabeled", "label": "aviato-consent:abc", "actor_type": "User", "actor_login": "al"},
    ]
    assert current_consent(events) is None


def test_current_consent_later_revoke_in_history_wins() -> None:
    # a naive single-page read could miss the trailing revoke; full history must
    events = [
        {"action": "labeled", "label": "aviato-consent:abc", "actor_type": "User", "actor_login": "al"},
        {"action": "labeled", "label": "noise", "actor_type": "User", "actor_login": "al"},
        {"action": "unlabeled", "label": "aviato-consent:abc", "actor_type": "User", "actor_login": "al"},
    ]
    assert current_consent(events) is None


def test_current_consent_most_recent_grant_wins() -> None:
    events = [
        {"action": "labeled", "label": "aviato-consent:old", "actor_type": "User", "actor_login": "al"},
        {"action": "labeled", "label": "aviato-consent:new", "actor_type": "User", "actor_login": "bo"},
    ]
    grant = current_consent(events)
    assert grant.diff_id == "new"


def test_current_consent_ignores_non_consent_labels() -> None:
    assert current_consent([{"action": "labeled", "label": "bug", "actor_type": "User"}]) is None


def test_label_events_normalizes_timeline() -> None:
    timeline = [
        {"event": "labeled", "label": {"name": "aviato-consent:x"}, "actor": {"login": "al", "type": "User"}},
        {"event": "commented", "body": "hi"},
    ]
    events = _label_events(timeline)
    assert events == [{"action": "labeled", "label": "aviato-consent:x", "actor_type": "User", "actor_login": "al"}]


def test_adapter_satisfies_platform_protocol() -> None:
    assert isinstance(GitHubPlatform(), Platform)


def test_map_branch_settings_from_rules() -> None:
    rules = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "pull_request", "parameters": {"required_approving_review_count": 2}},
    ]
    mapped = map_branch_settings(rules, {})
    assert mapped == {
        "requires_pull_request": True,
        "required_reviews": 2,
        "block_force_push": True,
        "block_deletion": True,
    }


def test_map_branch_settings_unprotected() -> None:
    mapped = map_branch_settings([], {})
    assert mapped["requires_pull_request"] is False
    assert mapped["block_force_push"] is False
    assert mapped["block_deletion"] is False


def test_map_branch_settings_classic_protection() -> None:
    protection = {
        "required_pull_request_reviews": {"required_approving_review_count": 1},
        "allow_force_pushes": {"enabled": False},
    }
    mapped = map_branch_settings([], protection)
    assert mapped["requires_pull_request"] is True
    assert mapped["required_reviews"] == 1
    assert mapped["block_force_push"] is True


def test_read_settings_composes_gh_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(
        github,
        "active_branch_rules",
        lambda repo, branch: [{"type": "pull_request", "parameters": {"required_approving_review_count": 1}}],
    )
    monkeypatch.setattr(github, "classic_branch_protection", lambda repo, branch: {})

    settings = GitHubPlatform().read_settings("o/r")
    assert settings["default_branch"]["required_reviews"] == 1


def test_read_settings_empty_when_no_default_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "default_branch", lambda repo: "")
    assert GitHubPlatform().read_settings("o/r") == {}


def test_get_issue_populates_consent_from_paginated_timeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "gh_json", lambda endpoint, **__: _route_gh_json(endpoint))
    monkeypatch.setattr(
        github,
        "gh_json_paginated",
        lambda endpoint, **__: [
            {"event": "labeled", "label": {"name": "aviato-consent:abc"}, "actor": {"login": "al", "type": "User"}}
        ],
    )
    issue = GitHubPlatform().get_issue("o/r", "aviato-settings-drift")
    assert issue is not None
    assert issue.consent_diff_id == "abc"
    assert issue.consent_actor_type == "User"
    assert issue.consent_role == "admin"
    assert issue.consent_role_lookup_ok is True


def _route_gh_json(endpoint: str):
    if endpoint.startswith("repos/o/r/issues?"):
        return [{"number": 7, "state": "open"}]
    if endpoint.endswith("/permission"):
        return {"permission": "admin"}
    return None


def test_get_issue_role_lookup_failure_is_not_authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    def gh_json(endpoint, **__):
        if endpoint.startswith("repos/o/r/issues?"):
            return [{"number": 7, "state": "open"}]
        return None  # permission lookup fails

    monkeypatch.setattr(github, "gh_json", gh_json)
    monkeypatch.setattr(
        github,
        "gh_json_paginated",
        lambda endpoint, **__: [
            {"event": "labeled", "label": {"name": "aviato-consent:abc"}, "actor": {"login": "al", "type": "User"}}
        ],
    )
    issue = GitHubPlatform().get_issue("o/r", "k")
    assert issue.consent_role_lookup_ok is False


def test_apply_settings_issues_put_with_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(github, "default_branch", lambda repo: "main")

    def fake_run(cmd, **__):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(github, "run", fake_run)
    GitHubPlatform().apply_settings("o/r", {"required_reviews": 2})
    cmd = captured["cmd"]
    assert "PUT" in cmd
    assert "repos/o/r/branches/main/protection" in cmd
