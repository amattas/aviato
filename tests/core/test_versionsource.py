from __future__ import annotations

import json
from pathlib import Path

import pytest

from aviato.core.errors import AviatoError
from aviato.core.versionsource import bump_files, bump_text


def test_bump_pyproject_version() -> None:
    text = '[project]\nname = "x"\nversion = "1.2.3"\n'
    assert 'version = "2.0.0"' in bump_text("pyproject.toml", text, "2.0.0")


def test_bump_pyproject_without_version_errors() -> None:
    with pytest.raises(AviatoError):
        bump_text("pyproject.toml", "[project]\nname = 'x'\n", "2.0.0")


def test_bump_package_json_version() -> None:
    out = bump_text("package.json", '{"name": "x", "version": "0.1.0"}', "0.2.0")
    assert json.loads(out)["version"] == "0.2.0"


def test_bump_unsupported_file_unchanged() -> None:
    assert bump_text("Info.plist", "<plist/>", "9.9.9") == "<plist/>"


def test_bump_files_rewrites_existing_locations(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    changed = bump_files(tmp_path, ["pyproject.toml", "missing.toml"], "1.1.0")
    assert changed == ["pyproject.toml"]
    assert 'version = "1.1.0"' in (tmp_path / "pyproject.toml").read_text()
