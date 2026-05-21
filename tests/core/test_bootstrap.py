from __future__ import annotations

from pathlib import Path

from aviato.core.bootstrap import is_library


def _make_library(root: Path) -> None:
    (root / "aviato" / "core").mkdir(parents=True)
    (root / "aviato" / "core" / "__init__.py").write_text("")
    (root / "profiles").mkdir()
    (root / "bundles").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n")


def test_full_layout_is_library(tmp_path: Path) -> None:
    _make_library(tmp_path)
    assert is_library(tmp_path) is True


def test_name_independent(tmp_path: Path) -> None:
    renamed = tmp_path / "totally-different-name"
    renamed.mkdir()
    _make_library(renamed)
    assert is_library(renamed) is True


def test_missing_profiles_is_not_library(tmp_path: Path) -> None:
    _make_library(tmp_path)
    import shutil

    shutil.rmtree(tmp_path / "profiles")
    assert is_library(tmp_path) is False


def test_missing_core_package_is_not_library(tmp_path: Path) -> None:
    (tmp_path / "profiles").mkdir()
    (tmp_path / "bundles").mkdir()
    (tmp_path / "pyproject.toml").write_text("")
    assert is_library(tmp_path) is False
