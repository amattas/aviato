from __future__ import annotations

from pathlib import Path

import pytest

from aviato.cli import main


def test_next_version_from_commit_flags(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["next-version", "--current", "1.2.3", "--commit", "feat: a", "--commit", "fix: b"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "v1.3.0"


def test_next_version_breaking(capsys: pytest.CaptureFixture[str]) -> None:
    main(["next-version", "--current", "1.2.3", "--commit", "feat!: drop x"])
    assert capsys.readouterr().out.strip() == "v2.0.0"


def test_bump_version_rewrites_pyproject(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: v0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8")
    rc = main(["bump-version", "0.2.0", str(tmp_path)])
    assert rc == 0
    assert 'version = "0.2.0"' in (tmp_path / "pyproject.toml").read_text()
