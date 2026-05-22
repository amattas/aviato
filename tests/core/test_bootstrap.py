from __future__ import annotations

from pathlib import Path

from aviato.core.bootstrap import is_library


def _make_library(root: Path) -> None:
    (root / "aviato" / "core").mkdir(parents=True)
    (root / "aviato" / "core" / "__init__.py").write_text("")
    (root / "aviato" / "library" / "bundles").mkdir(parents=True)
    (root / "aviato" / "library" / "scaffold").mkdir(parents=True)
    (root / "policy.yml").write_text("release: {}\n")


def test_full_layout_is_library(tmp_path: Path) -> None:
    _make_library(tmp_path)
    assert is_library(tmp_path) is True


def test_name_independent(tmp_path: Path) -> None:
    renamed = tmp_path / "totally-different-name"
    renamed.mkdir()
    _make_library(renamed)
    assert is_library(renamed) is True


def test_missing_module_tree_is_not_library(tmp_path: Path) -> None:
    _make_library(tmp_path)
    import shutil

    shutil.rmtree(tmp_path / "aviato" / "library")
    assert is_library(tmp_path) is False


def test_missing_core_package_is_not_library(tmp_path: Path) -> None:
    (tmp_path / "aviato" / "library" / "bundles").mkdir(parents=True)
    (tmp_path / "aviato" / "library" / "scaffold").mkdir(parents=True)
    (tmp_path / "policy.yml").write_text("release: {}\n")
    assert is_library(tmp_path) is False


def test_vendored_package_without_policy_is_not_library(tmp_path: Path) -> None:
    # A partial vendored copy of the aviato/ package tree (core + library) WITHOUT the
    # repo-root policy.yml must NOT be detected as the Library, or it would wrongly skip
    # the §2.6 version-pin gate (§5.10 third anchor).
    _make_library(tmp_path)
    (tmp_path / "policy.yml").unlink()
    assert is_library(tmp_path) is False
