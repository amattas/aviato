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
    # --pin v0 (legacy form) is canonicalized to bare on write; a leading v is never emitted (§6.1).
    assert decl["version"] == "0"
    assert decl["variables"]["distribution-name"] == "acme"

    # managed file scaffolded with marker (bare pin); seed-once LICENSE written without marker
    assert (tmp_path / "ruff.toml").read_text().startswith("# aviato:managed profile=python-library version=0")
    assert "wrote .github/aviato.yaml" in out


def test_reonboard_preserves_docs_opt_in(tmp_path: Path) -> None:
    # §5.2/§6.1 (M-D): re-onboarding an adopted docs:true repo WITHOUT --docs must NOT silently
    # flip docs back to false. --docs only enables; a re-run preserves the existing choice.
    base = [
        "onboard",
        str(tmp_path),
        "--profile",
        "python-library",
        "--write",
        "--allow-dirty",
        "--pin",
        "0",
        "--var",
        "distribution-name=acme",
        "--var",
        "import-name=acme",
    ]
    assert main(base + ["--docs"]) == 0
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["docs"] is True
    # Re-onboard WITHOUT --docs → docs must stay true (preserved like overrides).
    assert main(base) == 0
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["docs"] is True


def test_reonboard_docs_true_also_scaffolds_docs_workflow(tmp_path: Path) -> None:
    # §5.2/§6.1/§13.3 (FIX-1): a docs:true declaration re-onboarded WITHOUT --docs must keep
    # docs:true AND scaffold the docs workflow — the artifacts must match the declaration, not
    # silently omit docs (the partial-fix bug where scaffold used args.docs).
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "aviato.yaml").write_text(
        "profile: python-library\nversion: '0'\ndocs: true\nvariables:\n  distribution-name: a\n  import-name: a\n",
        encoding="utf-8",
    )
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
        ]  # NO --docs
    )
    assert rc == 0
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["docs"] is True
    assert list((tmp_path / ".github" / "workflows").glob("*docs*")), "docs:true must scaffold the docs workflow"


def test_onboard_write_fails_on_missing_required_var(tmp_path: Path) -> None:
    rc = main(["onboard", str(tmp_path), "--profile", "python-library", "--write", "--pin", "0"])
    assert rc == 2
    assert not (tmp_path / ".github" / "aviato.yaml").exists()


def test_fresh_onboard_write_requires_explicit_pin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
    err = capsys.readouterr().err
    assert rc == 2
    assert "--pin" in err
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
            "--pin",
            "0",
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
            "--pin",
            "0",
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
