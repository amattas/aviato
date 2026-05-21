from __future__ import annotations

import subprocess

import pytest

from aviato import github
from aviato.core.ports import Platform
from aviato.github_platform import GitHubPlatform, map_branch_settings


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
