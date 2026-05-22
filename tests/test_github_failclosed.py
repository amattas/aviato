from __future__ import annotations

import subprocess

import pytest

from aviato import github


def test_gh_json_optional_returns_default_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        github, "run", lambda *_, **__: subprocess.CompletedProcess(["gh"], 1, "", "gh: HTTP 404: Not Found")
    )
    assert github.gh_json_optional("repos/o/r/branches/main/protection", default={}) == {}


def test_gh_json_optional_raises_on_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # an ambiguous read (auth/5xx) must NOT be swallowed as empty state (§2.7)
    monkeypatch.setattr(
        github, "run", lambda *_, **__: subprocess.CompletedProcess(["gh"], 1, "", "HTTP 401: Bad credentials")
    )
    with pytest.raises(github.GitHubAPIError):
        github.gh_json_optional("repos/o/r/branches/main/protection", default={})


def test_classic_branch_protection_raises_on_ambiguous_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        github, "run", lambda *_, **__: subprocess.CompletedProcess(["gh"], 1, "", "HTTP 500: server error")
    )
    with pytest.raises(github.GitHubAPIError):
        github.classic_branch_protection("o/r", "main")


def test_active_branch_rules_empty_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        github, "run", lambda *_, **__: subprocess.CompletedProcess(["gh"], 1, "", "HTTP 404: Not Found")
    )
    assert github.active_branch_rules("o/r", "main") == []
