from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import venv
import zipfile
from email.parser import Parser
from functools import partial
from importlib import metadata
from importlib.metadata import version as distribution_version
from pathlib import Path

import pytest

import aviato
from aviato import __version__
from aviato.cli import _version_pin_error, main
from aviato.core.declaration import Declaration
from aviato.core.diagnosis import ExpectedArtifact as _ExpectedArtifact

ExpectedArtifact = partial(_ExpectedArtifact, input_hash="0" * 64)


def _managed(profile: str, version: str) -> str:
    return f"# aviato:managed profile={profile} version={version} hash=abc123\nline-length = 120\n"


def test_runtime_version_matches_distribution_metadata() -> None:
    assert __version__ == distribution_version("aviato")


def test_source_version_fallback_reads_root_pyproject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "aviato"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3-beta4"\n', encoding="utf-8")
    monkeypatch.setattr(aviato, "__file__", str(package / "__init__.py"))

    assert aviato._source_version() == "1.2.3-beta4"


def test_source_version_fallback_rejects_malformed_semver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "aviato"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "01.2.3"\n', encoding="utf-8")
    monkeypatch.setattr(aviato, "__file__", str(package / "__init__.py"))

    with pytest.raises(RuntimeError, match="not valid SemVer"):
        aviato._source_version()


def test_runtime_version_does_not_swallow_metadata_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: str) -> str:
        raise RuntimeError("malformed distribution metadata")

    monkeypatch.setattr(metadata, "version", fail)

    with pytest.raises(RuntimeError, match="malformed distribution metadata"):
        aviato._runtime_version()


def test_runtime_version_falls_back_only_when_distribution_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_: str) -> str:
        raise metadata.PackageNotFoundError("aviato")

    monkeypatch.setattr(metadata, "version", missing)
    monkeypatch.setattr(aviato, "_source_version", lambda: "2.3.4")

    assert aviato._runtime_version() == "2.3.4"


def test_built_wheel_runtime_version_matches_metadata(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheel"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(wheel_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))

    environment = tmp_path / "venv"
    uv = shutil.which("uv")
    if uv is not None:
        subprocess.run([uv, "venv", "--python", sys.executable, str(environment)], check=True, capture_output=True)
    else:
        venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin" / "python"
    if uv is not None:
        install = [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)]
    else:
        install = [str(python), "-m", "pip", "install", "--no-deps", str(wheel)]
    subprocess.run(install, check=True, capture_output=True, text=True)
    outside_checkout = tmp_path / "outside-checkout"
    outside_checkout.mkdir()
    installed = subprocess.run(
        [
            str(python),
            "-c",
            "import json; import aviato; print(json.dumps([aviato.__version__, aviato.__file__]))",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=outside_checkout,
    ).stdout.strip()
    installed_version, module_file = json.loads(installed)

    assert Path(module_file).resolve().is_relative_to(environment.resolve())
    assert "site-packages" in Path(module_file).parts
    assert installed_version == metadata["Version"]


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


def test_next_version_stdin_parses_git_log_nul_records(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression (release derive, §5.9): the workflow pipes `git log --format=%B%x00`,
    # which emits "<body>\0\n" per record — every record after the first starts with a
    # newline. The derive previously classified ONLY the first record (HEAD): a merge
    # commit or fix at HEAD masked every feat behind it, so the release pipeline
    # silently no-opped (or under-bumped) on merge-commit repos.
    payload = (
        "Merge pull request #18 from x/y\n\x00\nfix(scope): tip-adjacent fix\n\n\x00\nfeat: earlier feature\n\x00\n"
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    rc = main(["next-version", "--current", "0.0.0"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_bump_version_rewrites_pyproject(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: 0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8")
    rc = main(["bump-version", "0.2.0", str(tmp_path)])
    assert rc == 0
    assert 'version = "0.2.0"' in (tmp_path / "pyproject.toml").read_text()


def test_bump_version_rejects_symlinked_version_source_leaf(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: 0\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    original = b'[project]\nversion = "0.1.0"\n'
    outside.write_bytes(original)
    (tmp_path / "pyproject.toml").symlink_to(outside)

    rc = main(["bump-version", "0.2.0", str(tmp_path)])

    assert rc != 0
    assert "pyproject.toml" in capsys.readouterr().err
    assert outside.read_bytes() == original


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


def test_bump_version_refuses_malformed_and_bare_major(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # finding 21: a garbage version was previously spliced into manifests and reported
    # as success; a bare-major pin (a Library ref, not a release version) is refused too.
    from aviato.cli import main

    rc = main(["bump-version", "not-a-version", str(tmp_path)])
    assert rc == 2
    assert "not a release version" in capsys.readouterr().err

    rc = main(["bump-version", "1", str(tmp_path)])
    assert rc == 2
    assert "not a release version" in capsys.readouterr().err


def test_bump_version_accepts_policy_valid_prereleases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # second-review fix: X.Y.Z-alphaN/-betaN are policy-valid bump targets and must
    # pass the input gate (the failure here is the missing declaration, proving the
    # version validation accepted it); leading-zero components are rejected (finding 47).
    from aviato.cli import main

    rc = main(["bump-version", "1.2.3-alpha1", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not a release version" not in err
    assert "no declaration" in err

    rc = main(["bump-version", "01.2.3", str(tmp_path)])
    assert rc == 2
    assert "not a release version" in capsys.readouterr().err
