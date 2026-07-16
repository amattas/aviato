from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import aviato.cli as cli
from aviato.cli import main
from aviato.core.registry import Registry
from aviato.core.scaffold import ScaffoldItem, render_managed
from aviato.github_platform import GitHubPlatform
from aviato.paths import MODULE_SOURCE_ROOT

pytestmark = pytest.mark.usefixtures("task3_pinned_context")


def test_existing_seed_proposal_preserves_and_enumerates_seed_once_files(
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

    def fake_proposal(self: GitHubPlatform, repo: str, branch: str, title: str, body: str) -> str:
        captured.update(
            repo=repo,
            branch=branch,
            title=title,
            body=body,
            declaration=(self.workdir / ".github/aviato.yaml").read_text(encoding="utf-8"),
            inventory=(self.workdir / ".github/aviato.managed.yml").read_text(encoding="utf-8"),
            sidecar=(self.workdir / ".github/aviato.seed.json").read_text(encoding="utf-8"),
            license=(self.workdir / "LICENSE").read_text(encoding="utf-8"),
        )
        return branch

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)

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
    assert rc == 0
    assert captured_output.err == ""
    assert captured["repo"] == "acme-org/widget"
    assert captured["license"] == "operator's own license"
    assert "profile: python-library" in str(captured["declaration"])
    assert "snapshot_commit:" in str(captured["inventory"])
    assert "LICENSE" in str(captured["sidecar"])
    assert "`LICENSE`" in str(captured["body"])


def test_fresh_proposal_includes_seed_sidecar_declaration_and_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, bool] = {}

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            dest.mkdir(parents=True)
            subprocess.run(["git", "-C", str(dest), "init", "-q"], check=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(self: GitHubPlatform, *_args: object, **_kwargs: object) -> str:
        captured.update(
            declaration=(self.workdir / ".github/aviato.yaml").is_file(),
            sidecar=(self.workdir / ".github/aviato.seed.json").is_file(),
            inventory=(self.workdir / ".github/aviato.managed.yml").is_file(),
        )
        return "branch"

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)

    assert (
        main(
            [
                "onboard",
                "acme/widget",
                "--open-pr",
                "--profile",
                "python-library",
                "--pin",
                "0",
                "--var",
                "distribution-name=acme",
                "--var",
                "import-name=acme",
            ]
        )
        == 0
    )
    assert captured == {"declaration": True, "sidecar": True, "inventory": True}


def test_local_and_proposal_onboarding_execute_the_same_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [
        "--profile",
        "python-library",
        "--pin",
        "0",
        "--var",
        "distribution-name=acme",
        "--var",
        "import-name=acme",
        "--var",
        "owner=acme",
        "--var",
        "repo=widget",
    ]
    assert main(["onboard", str(tmp_path), "--write", "--allow-dirty", *args]) == 0
    capsys.readouterr()
    local = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(tmp_path).parts
    }
    proposal: dict[str, bytes] = {}

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            dest.mkdir(parents=True)
            subprocess.run(["git", "-C", str(dest), "init", "-q"], check=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(self: GitHubPlatform, *_args: object, **_kwargs: object) -> str:
        proposal.update(
            {
                path.relative_to(self.workdir).as_posix(): path.read_bytes()
                for path in self.workdir.rglob("*")
                if path.is_file() and ".git" not in path.relative_to(self.workdir).parts
            }
        )
        return "branch"

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)
    assert main(["onboard", "acme/widget", "--open-pr", *args]) == 0
    assert proposal == local


def test_proposal_includes_clean_obsolete_deletions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "-C", str(source), "init", "-q"], check=True)
    args = [
        "--profile",
        "python-library",
        "--pin",
        "0",
        "--var",
        "distribution-name=acme",
        "--var",
        "import-name=acme",
    ]
    assert main(["onboard", str(source), "--write", "--allow-dirty", *args]) == 0
    subprocess.run(["git", "-C", str(source), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Aviato Test",
            "-c",
            "user.email=aviato@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "onboard",
        ],
        check=True,
        capture_output=True,
    )
    target_library = tmp_path / "target-library"
    shutil.copytree(MODULE_SOURCE_ROOT, target_library)
    bundle = target_library / "bundles/scaffold/python-library-sc.yaml"
    bundle.write_text(
        "name: python-library-sc\nextends: python-sc\nadd: []\nremove: [python-lint-config]\n",
        encoding="utf-8",
    )
    target_context = SimpleNamespace(
        registry=Registry(target_library),
        policy_root=target_library,
        snapshot=SimpleNamespace(commit_sha="b" * 40),
    )
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            shutil.copytree(source, Path(cmd[4]), dirs_exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(self: GitHubPlatform, _repo: str, _branch: str, _title: str, body: str) -> str:
        captured["ruff_exists"] = (self.workdir / "ruff.toml").exists()
        captured["body"] = body
        return "branch"

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "_open_consumer_context", lambda _root, _declaration: target_context)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)

    assert main(["onboard", "acme/widget", "--open-pr", *args]) == 0
    assert captured["ruff_exists"] is False
    assert "ruff.toml" in str(captured["body"])


@pytest.mark.parametrize("collision", ["unmanaged", "dirty", "foreign", "malformed"])
def test_unmanaged_dirty_foreign_and_malformed_collisions_block_before_proposal(
    collision: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    proposal_called = False
    marker_item = ScaffoldItem(
        "ruff.toml",
        "original\n",
        "#",
        input_hash="0" * 64,
        artifact_id="artifact/python-lint-config/v1",
        pipeline_owners=("scaffold",),
    )
    bodies = {
        "unmanaged": "operator-owned\n",
        "dirty": render_managed(marker_item, profile="python-library", version="0") + "# edited\n",
        "foreign": render_managed(marker_item, profile="node-service", version="0"),
        "malformed": "# aviato:managed malformed\noperator-owned\n",
    }

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            dest.mkdir(parents=True)
            subprocess.run(["git", "-C", str(dest), "init", "-q"], check=True)
            (dest / "ruff.toml").write_text(bodies[collision], encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(*_args: object, **_kwargs: object) -> str:
        nonlocal proposal_called
        proposal_called = True
        return "branch"

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)
    rc = main(
        [
            "onboard",
            "acme/widget",
            "--open-pr",
            "--profile",
            "python-library",
            "--pin",
            "0",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )

    assert rc == 2
    assert "ruff.toml" in capsys.readouterr().err
    assert proposal_called is False


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
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)

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
    assert "not confined" in capsys.readouterr().err.lower()
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
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)
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
    assert "profile identity" in captured.err.lower()
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

    def fake_proposal(self: GitHubPlatform, repo: str, branch: str, title: str, body: str) -> str:
        captured.update(body=body)
        return branch

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)
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

    def fake_proposal(self: GitHubPlatform, repo: str, branch: str, title: str, body: str) -> str:
        captured.update(body=body)
        return branch

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)
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
    error = capsys.readouterr().err
    assert ("repin" in error) if allow_migrate else ("--migrate-profile" in error)
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
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)
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
