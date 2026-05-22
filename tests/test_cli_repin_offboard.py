from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aviato.cli import main


def _adopt(tmp_path: Path) -> None:
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
    assert rc == 0


def test_repin_dry_run_then_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _adopt(tmp_path)
    capsys.readouterr()

    # Dry run: reports the move, does not change the declaration.
    rc = main(["repin", str(tmp_path), "v1.0.0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "re-pin v0 -> v1.0.0" in out
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["version"] == "v0"

    # Write: records the new pin and re-scaffolds the pin-bearing workflows with it.
    rc = main(["repin", str(tmp_path), "v1.0.0", "--write"])
    assert rc == 0
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["version"] == "v1.0.0"
    ci = (tmp_path / ".github" / "workflows" / "aviato-ci.yml").read_text()
    assert "@v1.0.0" in ci  # the pin in `uses:` refs moved
    assert "version=v1.0.0" in ci  # marker updated where the body changed


def test_offboard_dry_run_then_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _adopt(tmp_path)
    capsys.readouterr()
    assert (tmp_path / "ruff.toml").read_text().startswith("# aviato:managed")

    # Dry run: warns, changes nothing.
    rc = main(["offboard", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert (tmp_path / ".github" / "aviato.yaml").exists()

    # Write (strip markers): managed files become plain, declaration removed.
    rc = main(["offboard", str(tmp_path), "--write"])
    assert rc == 0
    assert not (tmp_path / ".github" / "aviato.yaml").exists()
    assert not (tmp_path / "ruff.toml").read_text().startswith("# aviato:managed")


def test_offboard_delete_files_removes_managed(tmp_path: Path) -> None:
    _adopt(tmp_path)
    assert (tmp_path / "ruff.toml").exists()
    rc = main(["offboard", str(tmp_path), "--delete-files", "--write"])
    assert rc == 0
    assert not (tmp_path / "ruff.toml").exists()
