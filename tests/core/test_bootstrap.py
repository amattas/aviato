from __future__ import annotations

from pathlib import Path

from aviato.core.bootstrap import is_library


def _make_library(root: Path) -> None:
    (root / "aviato" / "core").mkdir(parents=True)
    (root / "aviato" / "core" / "__init__.py").write_text("")
    (root / "aviato" / "library" / "bundles").mkdir(parents=True)
    (root / "aviato" / "library" / "scaffold").mkdir(parents=True)
    # §5.10 anchor: policy.yml lives INSIDE the package (ships in the wheel; §5.6/§11.3).
    (root / "aviato" / "library" / "policy.yml").write_text("release: {}\n")


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
    (tmp_path / "aviato" / "library" / "policy.yml").write_text("release: {}\n")
    assert is_library(tmp_path) is False


def test_vendored_package_without_policy_is_not_library(tmp_path: Path) -> None:
    # A partial vendored copy of the aviato/ package tree (core + library) WITHOUT the
    # packaged policy.yml must NOT be detected as the Library, or it would wrongly skip
    # the §2.6 version-pin gate (§5.10 policy anchor).
    _make_library(tmp_path)
    (tmp_path / "aviato" / "library" / "policy.yml").unlink()
    assert is_library(tmp_path) is False


def test_reonboard_preserves_verified_bootstrap(tmp_path: Path) -> None:
    import shutil
    from argparse import Namespace

    from aviato.cli import _resolve_onboard_declaration
    from aviato.core.composition import resolve_profile
    from aviato.core.declaration import Declaration
    from aviato.core.registry import Registry

    _make_library(tmp_path)
    shutil.copytree(Path("aviato/library"), tmp_path / "aviato/library", dirs_exist_ok=True)
    registry = Registry(tmp_path / "aviato/library")
    existing = Declaration(
        profile="python-library",
        profile_identity=registry.profile("python-library").identity,
        version="0",
        bootstrap=True,
        variables={"distribution-name": "aviato", "import-name": "aviato"},
    )
    args = Namespace(
        profile="python-library",
        pin=None,
        var=[],
        target=".",
        migrate_profile=False,
        docs=False,
        allow_unresolved_pin=False,
    )

    declaration, _ = _resolve_onboard_declaration(
        args,
        registry,
        resolve_profile(registry, "python-library"),
        existing,
    )
    assert declaration.bootstrap is True
    assert declaration.version == "0"
    assert existing.bootstrap is True
