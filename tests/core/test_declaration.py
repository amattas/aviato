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
    decl = Declaration(profile="p", version="2", docs=True, variables={"a": "b"}, overrides={"settings": {}})
    path = tmp_path / "aviato.yaml"
    dump_declaration(decl, path)
    assert load_declaration(path) == decl


def test_unquoted_float_version_is_rejected_not_silently_corrupted(tmp_path: Path) -> None:
    # review #3: `version: 1.10` (unquoted) is parsed by YAML as float 1.1 — a silent corruption
    # (1.10 != 1.1) that used to be str()'d and stamped into markers/refs. Must fail loud.
    path = tmp_path / "aviato.yaml"
    path.write_text("profile: p\nversion: 1.10\n", encoding="utf-8")
    with pytest.raises(DeclarationError) as exc:
        load_declaration(path)
    assert "quoted" in str(exc.value).lower()
    # A correctly-quoted (but malformed 2-component) pin and a null version also fail loud.
    for bad in ("'1.10'", "1.0", ""):
        path.write_text(f"profile: p\nversion: {bad}\n", encoding="utf-8")
        with pytest.raises(DeclarationError):
            load_declaration(path)
    # Recognized pins still load (floating major, exact, legacy-v).
    for good in ("1", "'0'", "1.2.3", "v2.0.0"):
        path.write_text(f"profile: p\nversion: {good}\n", encoding="utf-8")
        assert load_declaration(path).profile == "p"


def test_non_mapping_variables_or_overrides_raise_declaration_error(tmp_path: Path) -> None:
    # review #13: a non-mapping `variables:`/`overrides:` must raise the module's DeclarationError
    # (which every caller catches), not a raw ValueError from dict() that escapes the contract.
    path = tmp_path / "aviato.yaml"
    for field_name in ("variables", "overrides"):
        path.write_text(f"profile: p\nversion: 1.0.0\n{field_name}: [a, b]\n", encoding="utf-8")
        with pytest.raises(DeclarationError) as exc:
            load_declaration(path)
        assert field_name in str(exc.value)


def test_bootstrap_field_parses_round_trips_and_omitted_when_false(tmp_path: Path) -> None:
    # §5.10/§5.4: the Library's own declaration carries bootstrap: true; a normal Consumer
    # declaration omits it (defaults False) so the field never appears as noise on adopted repos.
    from aviato.core.declaration import declaration_to_yaml

    assert load_declaration  # imported
    lib = Declaration(profile="p", version="2", bootstrap=True)
    path = tmp_path / "aviato.yaml"
    dump_declaration(lib, path)
    assert load_declaration(path) == lib  # round-trips bootstrap: true
    assert yaml.safe_load(path.read_text())["bootstrap"] is True
    # default-False declaration must NOT emit the key at all
    assert "bootstrap" not in yaml.safe_load(declaration_to_yaml(Declaration(profile="p", version="2")))
    # absent key reads as False
    _write(path, {"profile": "p", "version": "2"})
    assert load_declaration(path).bootstrap is False


def test_legacy_v_prefix_is_tolerated_on_read_but_never_emitted(tmp_path: Path) -> None:
    # §6.1: bare SemVer is canonical; a legacy leading `v` is read but stripped on emit, so the
    # declaration type self-enforces "never emitted" no matter how the caller built it.
    import yaml

    from aviato.core.declaration import declaration_to_yaml

    assert yaml.safe_load(declaration_to_yaml(Declaration(profile="p", version="v2")))["version"] == "2"
    assert yaml.safe_load(declaration_to_yaml(Declaration(profile="p", version="v1.2.3")))["version"] == "1.2.3"
    # A non-pin string (no digit after v) is left untouched — only the legacy pin form is stripped.
    assert yaml.safe_load(declaration_to_yaml(Declaration(profile="p", version="vegetable")))["version"] == "vegetable"
