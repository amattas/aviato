from __future__ import annotations

from pathlib import Path

import pytest

from aviato.cli import main


def test_next_version_from_commit_flags(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["next-version", "--current", "1.2.3", "--commit", "feat: a", "--commit", "fix: b"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "1.3.0"


def test_next_version_breaking(capsys: pytest.CaptureFixture[str]) -> None:
    main(["next-version", "--current", "1.2.3", "--commit", "feat!: drop x"])
    assert capsys.readouterr().out.strip() == "2.0.0"


def test_next_version_from_prerelease_current(capsys: pytest.CaptureFixture[str]) -> None:
    # A pre-release current is policy-valid and reachable via the release workflow's
    # `git describe`; it must produce a clean next version, not crash.
    rc = main(["next-version", "--current", "1.2.3-beta1", "--commit", "fix: x"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "1.2.4"


def test_next_version_bad_current_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    # A malformed --current is a clean operator error (exit 2), not an uncaught traceback.
    rc = main(["next-version", "--current", "nope", "--commit", "fix: x"])
    assert rc == 2


def test_bump_version_rewrites_pyproject(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: 0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8")
    rc = main(["bump-version", "0.2.0", str(tmp_path)])
    assert rc == 0
    assert 'version = "0.2.0"' in (tmp_path / "pyproject.toml").read_text()
