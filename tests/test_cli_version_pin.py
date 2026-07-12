from __future__ import annotations

from pathlib import Path

import pytest

from aviato.cli import _recorded_versions, main
from aviato.core.diagnosis import ExpectedArtifact
from aviato.core.errors import PathConfinementError


def _consumer(tmp_path: Path, pin: str) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(
        f"profile: python-library\nversion: {pin}\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    return tmp_path


def test_sync_refuses_incompatible_pin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # tool is 0.x; a v1 pin is a different major → refuse (§2.6)
    rc = main(["sync", str(_consumer(tmp_path, "v1"))])
    err = capsys.readouterr().err
    assert rc == 2
    assert "version-pin mismatch" in err
    assert not (tmp_path / "ruff.toml").exists()


def test_sync_override_proceeds_despite_mismatch(tmp_path: Path) -> None:
    rc = main(["sync", str(_consumer(tmp_path, "v1")), "--override-version-pin"])
    assert rc == 0
    assert (tmp_path / "ruff.toml").exists()


def test_sync_compatible_pin_proceeds(tmp_path: Path) -> None:
    rc = main(["sync", str(_consumer(tmp_path, "v0"))])
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
