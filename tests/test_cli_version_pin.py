from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest

from aviato.cli import _recorded_versions, _version_pin_error, main
from aviato.core.declaration import Declaration
from aviato.core.diagnosis import ExpectedArtifact as _ExpectedArtifact
from aviato.core.errors import PathConfinementError

pytestmark = pytest.mark.usefixtures("task3_pinned_context")

ExpectedArtifact = partial(_ExpectedArtifact, input_hash="0" * 64)


def _consumer(tmp_path: Path, pin: str) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(
        f"profile: python-library\nprofile-identity: aviato-profile/python-library/v1\nversion: {pin}\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    return tmp_path


def _library_shape(root: Path) -> None:
    (root / "aviato/core").mkdir(parents=True)
    (root / "aviato/core/__init__.py").write_text("", encoding="utf-8")
    (root / "aviato/library/bundles").mkdir(parents=True)
    (root / "aviato/library/scaffold").mkdir(parents=True)
    (root / "aviato/library/policy.yml").write_text("library: {}\n", encoding="utf-8")


@pytest.mark.parametrize(("bootstrap", "skipped"), [(False, False), (True, True)])
def test_version_pin_skip_requires_structure_and_bootstrap_declaration(
    tmp_path: Path, bootstrap: bool, skipped: bool
) -> None:
    _library_shape(tmp_path)
    declaration = Declaration(profile="python-library", version="9.0.0", bootstrap=bootstrap)

    error = _version_pin_error(tmp_path, declaration, [], override=False)

    assert (error is None) is skipped
    if not skipped:
        assert "version-pin mismatch" in str(error)


def test_sync_refuses_incompatible_pin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # tool is 0.x; a v1 pin is a different major → refuse (§2.6)
    rc = main(["sync", str(_consumer(tmp_path, "v1"))])
    err = capsys.readouterr().err
    assert rc == 2
    assert "version-pin mismatch" in err
    assert not (tmp_path / "ruff.toml").exists()


def test_sync_override_proceeds_despite_mismatch(tmp_path: Path) -> None:
    rc = main(["sync", str(_consumer(tmp_path, "v1")), "--override-version-pin", "--rebaseline-seeds"])
    assert rc == 0
    assert (tmp_path / "ruff.toml").exists()


def test_sync_compatible_pin_proceeds(tmp_path: Path) -> None:
    rc = main(["sync", str(_consumer(tmp_path, "v0")), "--rebaseline-seeds"])
    assert rc == 0
    assert (tmp_path / "ruff.toml").exists()


def test_sync_tolerates_non_utf8_managed_file(tmp_path: Path) -> None:
    # R3-4-1/R3-5-B: a non-UTF-8 file at a managed output path must not crash the version-pin
    # gate with a raw UnicodeDecodeError (which would abort sync/drift/fleet-scan with a traceback).
    # _recorded_versions skips it (it carries no valid marker), so sync proceeds cleanly.
    root = _consumer(tmp_path, "v0")
    (root / "ruff.toml").write_bytes(b"\xff\xfe# not valid utf-8 \x00\x80")
    rc = main(["sync", str(root)])  # must NOT raise UnicodeDecodeError
    assert rc in (0, 2)


def test_recorded_versions_rejects_symlinked_artifact_parent(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "cfg.toml").write_text("outside\n", encoding="utf-8")
    (tmp_path / "nested").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathConfinementError, match=r"read managed marker.*nested/cfg\.toml"):
        _recorded_versions(tmp_path, [ExpectedArtifact("nested/cfg.toml", "expected\n")])
