from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import aviato.cli as cli
from aviato.cli import main


def test_onboard_open_pr_builds_proposal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate `gh repo clone OWNER/REPO <dest>` by materializing a clone dir that
    # already contains a LICENSE (an operator-owned seed-once file that must be left
    # untouched), and capture the proposal instead of pushing it.
    def fake_run(cmd, **__):
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            (dest / ".github").mkdir(parents=True, exist_ok=True)
            (dest / "LICENSE").write_text("operator's own license", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    captured: dict = {}

    def fake_proposal(self, repo, branch, title, files, body):  # noqa: ANN001
        captured.update(repo=repo, branch=branch, title=title, files=files, body=body)
        return branch

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli.GitHubPlatform, "open_or_update_proposal", fake_proposal)

    rc = main(
        [
            "onboard",
            "acme-org/widget",
            "--open-pr",
            "--profile",
            "python-library",
            "--pin",
            "v0",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )
    assert rc == 0
    files = captured["files"]
    assert captured["repo"] == "acme-org/widget"
    assert captured["branch"] == "aviato/onboard-python-library"
    # the declaration and a managed (marker-stamped) artifact are in the proposal
    assert ".github/aviato.yaml" in files
    assert "profile: python-library" in files[".github/aviato.yaml"]
    assert "ruff.toml" in files
    # --pin v0 (legacy) is canonicalized to a bare marker pin; a leading v is never emitted (§6.1).
    assert files["ruff.toml"].startswith("# aviato:managed profile=python-library version=0")
    assert ".github/workflows/aviato-ci.yml" in files
    # the pre-existing seed-once LICENSE is NOT overwritten and is enumerated as untouched
    assert "LICENSE" not in files
    assert "LICENSE" in captured["body"]
