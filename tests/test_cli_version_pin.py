from __future__ import annotations

from pathlib import Path

import pytest

from aviato.cli import main


def _consumer(tmp_path: Path, pin: str) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(f"profile: python-library\nversion: {pin}\n", encoding="utf-8")
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
