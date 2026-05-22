from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from aviato.cli import main


def _git_init_clean(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    # An empty repo with no changes is a clean working tree.


def test_onboard_write_adopts_local_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--allow-dirty",
            "--pin",
            "v0",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0

    decl = yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())
    assert decl["profile"] == "python-library"
    assert decl["version"] == "v0"
    assert decl["variables"]["distribution-name"] == "acme"

    # managed file scaffolded with marker; seed-once LICENSE written without marker
    assert (tmp_path / "ruff.toml").read_text().startswith("# aviato:managed profile=python-library version=v0")
    assert "wrote .github/aviato.yaml" in out


def test_onboard_write_fails_on_missing_required_var(tmp_path: Path) -> None:
    rc = main(["onboard", str(tmp_path), "--profile", "python-library", "--write"])
    assert rc == 2
    assert not (tmp_path / ".github" / "aviato.yaml").exists()


def test_onboard_write_refuses_profile_change_without_migrate(tmp_path: Path) -> None:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: node-service\nversion: v0\n", encoding="utf-8")
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--allow-dirty",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    assert rc == 2


def test_onboard_write_refuses_dirty_tree_without_override(tmp_path: Path) -> None:
    # §5.2 adopt precondition: a non-clean working tree is refused unless --allow-dirty.
    _git_init_clean(tmp_path)
    (tmp_path / "untracked.txt").write_text("dirty", encoding="utf-8")
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    assert rc == 2
    assert not (tmp_path / ".github" / "aviato.yaml").exists()


def test_onboard_write_adopts_clean_git_repo(tmp_path: Path) -> None:
    _git_init_clean(tmp_path)
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    assert rc == 0
    assert (tmp_path / ".github" / "aviato.yaml").exists()


def test_onboard_without_write_only_prints_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["onboard", str(tmp_path), "--profile", "python-library"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Onboarding plan" in out
    assert not (tmp_path / ".github" / "aviato.yaml").exists()  # plan-only, no write
