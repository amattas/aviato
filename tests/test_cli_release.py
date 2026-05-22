from __future__ import annotations

from pathlib import Path

import pytest

from aviato import __version__
from aviato.cli import _version_pin_error, main
from aviato.core.declaration import Declaration
from aviato.core.diagnosis import ExpectedArtifact


def _managed(profile: str, version: str) -> str:
    return f"# aviato:managed profile={profile} version={version} hash=abc123\nline-length = 120\n"


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


def test_bump_version_idempotent_when_already_current(tmp_path: Path) -> None:
    # §2.5: re-bumping a manifest already at the target is a successful no-op (exit 0), not
    # "no version-source files found" exit 1 — a release retry on an already-bumped tree
    # must not fail the workflow.
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: 0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.2.0"\n', encoding="utf-8")
    assert main(["bump-version", "0.2.0", str(tmp_path)]) == 0


def test_bump_version_errors_when_version_source_file_absent(tmp_path: Path) -> None:
    # Distinct from the idempotent no-op: a declared version-source location that does NOT
    # exist on disk is still worth flagging (exit 1).
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: 0\n", encoding="utf-8")
    assert main(["bump-version", "0.2.0", str(tmp_path)]) == 1


def test_version_pin_error_fails_closed_on_unparseable_marker(tmp_path: Path) -> None:
    # A managed marker recording an unrecognized version must yield a CLEAN refusal,
    # never an uncaught CompatibilityError traceback (§2.6 fail-closed).
    (tmp_path / "ruff.toml").write_text(_managed("python-library", "garbage"), encoding="utf-8")
    expected = [ExpectedArtifact("ruff.toml", "body", False)]
    decl = Declaration(profile="python-library", version="0", docs=False, variables={}, overrides={})
    err = _version_pin_error(tmp_path, decl, expected, override=False)
    assert err is not None and "version" in err.lower()


def test_version_pin_error_checks_all_markers_not_just_first(tmp_path: Path) -> None:
    # Every recorded marker is checked; an incompatible one ANYWHERE refuses, even if the
    # first marker scanned happens to be compatible (§2.6).
    (tmp_path / "a.toml").write_text(_managed("python-library", __version__), encoding="utf-8")
    (tmp_path / "b.toml").write_text(_managed("python-library", "999.0.0"), encoding="utf-8")
    expected = [ExpectedArtifact("a.toml", "body", False), ExpectedArtifact("b.toml", "body", False)]
    decl = Declaration(profile="python-library", version="0", docs=False, variables={}, overrides={})
    err = _version_pin_error(tmp_path, decl, expected, override=False)
    assert err is not None and "999.0.0" in err
