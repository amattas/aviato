from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aviato.core.declaration import Declaration, dump_declaration, load_declaration
from aviato.core.errors import DeclarationError


def _write(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_loads_valid_declaration(tmp_path: Path) -> None:
    path = tmp_path / "aviato.yaml"
    _write(path, {"profile": "python-library", "version": "v1", "variables": {"dist": "x"}})
    decl = load_declaration(path)
    assert decl.profile == "python-library"
    assert decl.version == "v1"
    assert decl.docs is False  # default
    assert decl.variables == {"dist": "x"}
    assert decl.overrides == {}


def test_docs_opt_in(tmp_path: Path) -> None:
    path = tmp_path / "aviato.yaml"
    _write(path, {"profile": "p", "version": "v1", "docs": True})
    assert load_declaration(path).docs is True


def test_missing_profile_is_error(tmp_path: Path) -> None:
    path = tmp_path / "aviato.yaml"
    _write(path, {"version": "v1"})
    with pytest.raises(DeclarationError):
        load_declaration(path)


def test_missing_version_is_error(tmp_path: Path) -> None:
    path = tmp_path / "aviato.yaml"
    _write(path, {"profile": "p"})
    with pytest.raises(DeclarationError):
        load_declaration(path)


def test_non_mapping_is_error(tmp_path: Path) -> None:
    path = tmp_path / "aviato.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(DeclarationError):
        load_declaration(path)


def test_round_trip(tmp_path: Path) -> None:
    decl = Declaration(profile="p", version="v2", docs=True, variables={"a": "b"}, overrides={"settings": {}})
    path = tmp_path / "aviato.yaml"
    dump_declaration(decl, path)
    assert load_declaration(path) == decl
