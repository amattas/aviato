from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import aviato.cli as cli
from aviato.cli import main
from aviato.github_platform import GitHubPlatform

pytestmark = pytest.mark.usefixtures("task3_pinned_context")


def test_legacy_onboard_open_pr_requires_repin_without_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Simulate `gh repo clone OWNER/REPO <dest>` by materializing a clone dir that
    # already contains a LICENSE (an operator-owned seed-once file that must be left
    # untouched), and capture the proposal instead of pushing it.
    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            dest.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-C", str(dest), "init"], check=True, capture_output=True)
            (dest / ".github").mkdir(parents=True, exist_ok=True)
            (dest / "LICENSE").write_text("operator's own license", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    captured: dict[str, object] = {}

    def fake_proposal(
        self: GitHubPlatform, repo: str, branch: str, title: str, files: dict[str, str], body: str
    ) -> str:
        captured.update(repo=repo, branch=branch, title=title, files=files, body=body)
        return branch

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_or_update_proposal", fake_proposal)

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
    captured_output = capsys.readouterr()
    assert rc == 2
    assert "repin" in captured_output.err
    assert captured == {}


def test_onboard_open_pr_rejects_symlinked_artifact_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = tmp_path / "outside-license"
    original = b"outside license\n"
    outside.write_bytes(original)
    proposal_called = False

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            dest.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-C", str(dest), "init"], check=True, capture_output=True)
            (dest / ".github").mkdir(parents=True, exist_ok=True)
            (dest / "LICENSE").symlink_to(outside)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(*_args: object, **_kwargs: object) -> str:
        nonlocal proposal_called
        proposal_called = True
        return "branch"

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_or_update_proposal", fake_proposal)

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

    assert rc != 0
    assert "repin" in capsys.readouterr().err
    assert outside.read_bytes() == original
    assert proposal_called is False


@pytest.mark.parametrize("identity_line", ["", "profile-identity: aviato-profile/repurposed/v1\n"])
def test_reonboard_open_pr_refuses_legacy_or_mismatched_identity_without_proposal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], identity_line: str
) -> None:
    proposal_called = False

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            dest.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-C", str(dest), "init"], check=True, capture_output=True)
            (dest / ".github").mkdir(parents=True)
            (dest / ".github" / "aviato.yaml").write_text(
                "profile: python-library\n"
                f"{identity_line}"
                "version: 0\nvariables:\n  distribution-name: acme\n  import-name: acme\n",
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(*_args: object, **_kwargs: object) -> str:
        nonlocal proposal_called
        proposal_called = True
        return "branch"

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_or_update_proposal", fake_proposal)
    rc = main(
        [
            "onboard",
            "acme/widget",
            "--open-pr",
            "--profile",
            "python-library",
            "--pin",
            "0",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "repin" in captured.err.lower()
    assert proposal_called is False


def test_legacy_reonboard_open_pr_requires_repin_even_with_equal_identity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            dest.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-C", str(dest), "init"], check=True, capture_output=True)
            (dest / ".github").mkdir(parents=True)
            (dest / ".github" / "aviato.yaml").write_text(
                "profile: python-library\nprofile-identity: aviato-profile/python-library/v1\n"
                "version: 0\nvariables:\n  distribution-name: acme\n  import-name: acme\n",
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(
        self: GitHubPlatform, repo: str, branch: str, title: str, files: dict[str, str], body: str
    ) -> str:
        captured.update(files=files)
        return branch

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_or_update_proposal", fake_proposal)
    assert main(["onboard", "acme/widget", "--open-pr", "--profile", "python-library", "--pin", "0"]) == 2
    assert "repin" in capsys.readouterr().err
    assert captured == {}


@pytest.mark.parametrize("allow_migrate", [False, True])
def test_onboard_open_pr_profile_migration_requires_flag_and_renders_requested_profile(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], allow_migrate: bool
) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            dest.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-C", str(dest), "init"], check=True, capture_output=True)
            (dest / ".github").mkdir(parents=True)
            (dest / ".github" / "aviato.yaml").write_text(
                "profile: python-library\nprofile-identity: aviato-profile/python-library/v1\n"
                "version: 0\nvariables:\n  distribution-name: acme\n  import-name: acme\n",
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(
        self: GitHubPlatform, repo: str, branch: str, title: str, files: dict[str, str], body: str
    ) -> str:
        captured.update(files=files)
        return branch

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_or_update_proposal", fake_proposal)
    argv = [
        "onboard",
        "acme/widget",
        "--open-pr",
        "--profile",
        "node-service",
        "--pin",
        "0",
        "--var",
        "project-name=widget",
        "--var",
        "language-variant=typescript",
    ]
    if allow_migrate:
        argv.append("--migrate-profile")

    rc = main(argv)

    assert rc == 2
    assert "repin" in capsys.readouterr().err
    assert captured == {}


def test_onboard_open_pr_profile_migration_does_not_propose_over_protected_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    proposal_called = False

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            dest.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-C", str(dest), "init"], check=True, capture_output=True)
            (dest / ".github").mkdir(parents=True)
            (dest / ".github" / "aviato.yaml").write_text(
                "profile: python-library\nprofile-identity: aviato-profile/python-library/v1\n"
                "version: 0\nvariables:\n  distribution-name: acme\n  import-name: acme\n",
                encoding="utf-8",
            )
            (dest / ".editorconfig").write_text("operator-owned\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(*_args: object, **_kwargs: object) -> str:
        nonlocal proposal_called
        proposal_called = True
        return "branch"

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_or_update_proposal", fake_proposal)
    rc = main(
        [
            "onboard",
            "acme/widget",
            "--open-pr",
            "--profile",
            "node-service",
            "--pin",
            "0",
            "--migrate-profile",
            "--var",
            "project-name=widget",
            "--var",
            "language-variant=typescript",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "repin" in captured.err
    assert proposal_called is False
