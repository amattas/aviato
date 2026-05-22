from __future__ import annotations

import subprocess

import pytest

from aviato import github


def test_gh_json_raises_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 1, "", "authentication failed")

    monkeypatch.setattr(github, "run", fake_run)

    with pytest.raises(github.GitHubAPIError):
        github.gh_json("repos/amattas/aviato")


def test_gh_json_can_allow_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 1, "", "not found")

    monkeypatch.setattr(github, "run", fake_run)

    assert github.gh_json("repos/amattas/aviato/rulesets", default=[], allow_error=True) == []
