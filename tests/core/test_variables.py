from __future__ import annotations

import pytest

from aviato.core.errors import DeclarationError
from aviato.core.model import VariableSpec
from aviato.core.variables import resolve_variables, writeback_variables


def test_precedence_flags_over_declaration_over_env_over_autodetect() -> None:
    specs = (VariableSpec("name", "string"),)
    resolved = resolve_variables(
        specs,
        flags={"name": "f"},
        declaration={"name": "d"},
        env={"name": "e"},
        autodetect={"name": "a"},
    )
    assert resolved["name"] == "f"


def test_declaration_wins_when_no_flag() -> None:
    specs = (VariableSpec("name", "string"),)
    resolved = resolve_variables(
        specs, flags={}, declaration={"name": "d"}, env={"name": "e"}, autodetect={"name": "a"}
    )
    assert resolved["name"] == "d"


def test_autodetect_is_lowest() -> None:
    specs = (VariableSpec("name", "string"),)
    resolved = resolve_variables(specs, flags={}, declaration={}, env={}, autodetect={"name": "a"})
    assert resolved["name"] == "a"


def test_enum_value_outside_domain_is_error() -> None:
    specs = (VariableSpec("lv", "enum", domain=("typescript", "javascript")),)
    with pytest.raises(DeclarationError):
        resolve_variables(specs, flags={"lv": "ruby"}, declaration={}, env={}, autodetect={})


def test_enum_value_inside_domain_ok() -> None:
    specs = (VariableSpec("lv", "enum", domain=("typescript", "javascript")),)
    resolved = resolve_variables(specs, flags={"lv": "typescript"}, declaration={}, env={}, autodetect={})
    assert resolved["lv"] == "typescript"


def test_boolean_coercion() -> None:
    specs = (VariableSpec("flag", "boolean"),)
    resolved = resolve_variables(specs, flags={"flag": "true"}, declaration={}, env={}, autodetect={})
    assert resolved["flag"] is True


def test_missing_required_variable_fails_closed_listing_name() -> None:
    specs = (VariableSpec("dist", "string"),)
    with pytest.raises(DeclarationError) as exc:
        resolve_variables(specs, flags={}, declaration={}, env={}, autodetect={})
    assert "dist" in str(exc.value)


def test_optional_variable_uses_default() -> None:
    specs = (VariableSpec("opt", "string", required=False, default="x"),)
    resolved = resolve_variables(specs, flags={}, declaration={}, env={}, autodetect={})
    assert resolved["opt"] == "x"


def test_writeback_excludes_nothing_for_non_secret() -> None:
    specs = (VariableSpec("dist", "string"),)
    assert writeback_variables(specs, {"dist": "x"}) == {"dist": "x"}


def test_persisting_secret_typed_variable_is_hard_error() -> None:
    specs = (VariableSpec("token", "string", secret=True),)
    with pytest.raises(DeclarationError):
        writeback_variables(specs, {"token": "abc"})
