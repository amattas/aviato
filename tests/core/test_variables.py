from __future__ import annotations

from datetime import date

import pytest

from aviato.core import variables as variables_module
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


@pytest.mark.parametrize("value", [42, 3.5, True, date(2026, 7, 12)])
def test_string_variables_canonicalize_non_none_yaml_scalars(value: object) -> None:
    specs = (VariableSpec("name", "string"),)
    resolved = resolve_variables(specs, flags={"name": value}, declaration={}, env={}, autodetect={})
    assert resolved["name"] == str(value)


def test_string_variables_preserve_explicit_none_as_unset() -> None:
    specs = (VariableSpec("name", "string", required=False),)
    resolved = resolve_variables(specs, flags={"name": None}, declaration={}, env={}, autodetect={})
    assert resolved["name"] is None


def test_enum_canonicalizes_scalar_before_string_domain_check() -> None:
    specs = (VariableSpec("choice", "enum", domain=("1", "2")),)
    resolved = resolve_variables(specs, flags={"choice": 1}, declaration={}, env={}, autodetect={})
    assert resolved["choice"] == "1"


@pytest.mark.parametrize("value", [["nested"], {"nested": "value"}, {"nested"}])
def test_string_variables_reject_non_scalar_values(value: object) -> None:
    specs = (VariableSpec("name", "string"),)
    with pytest.raises(DeclarationError, match="name.*scalar"):
        resolve_variables(specs, flags={"name": value}, declaration={}, env={}, autodetect={})


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


def test_writeback_allows_unset_optional_secret() -> None:
    # §8.15: a secret must never be PERSISTED — but an optional secret that was not
    # provided resolves to None and would never be written. resolve_variables emits a
    # key for every spec (including unset optionals), so the guard must key on a
    # non-None value, not mere presence; otherwise onboarding any profile that declares
    # a secret variable hard-errors even when no secret value exists.
    specs = (VariableSpec("token", "string", secret=True, required=False),)
    assert writeback_variables(specs, {"token": None, "dist": "x"}) == {"dist": "x"}


def test_declared_variables_reject_unknown_name_before_resolution() -> None:
    specs = (VariableSpec("language-variant", "enum", domain=("typescript", "javascript")),)
    with pytest.raises(DeclarationError, match="language-varaint"):
        variables_module.resolve_declared_variables(specs, {"language-varaint": "typescript"})


def test_declared_variables_coerce_boolean_through_shared_resolver() -> None:
    specs = (VariableSpec("docs-mode", "boolean", required=False, default=False),)
    resolved = variables_module.resolve_declared_variables(specs, {"docs-mode": "true"})
    assert resolved == {"docs-mode": True}


def test_declared_variables_reject_invalid_boolean() -> None:
    specs = (VariableSpec("docs-mode", "boolean", required=False, default=False),)
    with pytest.raises(DeclarationError, match="docs-mode"):
        variables_module.resolve_declared_variables(specs, {"docs-mode": "not-a-bool"})


def test_declared_variables_reject_missing_required_value() -> None:
    specs = (VariableSpec("required-name", "string"),)
    with pytest.raises(DeclarationError, match="required-name"):
        variables_module.resolve_declared_variables(specs, {})


def test_declared_variables_reject_non_none_secret_value() -> None:
    specs = (VariableSpec("token", "string", secret=True, required=False),)
    with pytest.raises(DeclarationError, match="token"):
        variables_module.resolve_declared_variables(specs, {"token": "secret"})


def test_declared_variables_allow_unset_optional_secret() -> None:
    specs = (VariableSpec("token", "string", secret=True, required=False),)
    assert variables_module.resolve_declared_variables(specs, {"token": None}) == {"token": None}
