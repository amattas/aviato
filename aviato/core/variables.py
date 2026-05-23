from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import DeclarationError
from .model import VariableSpec

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


def _coerce(spec: VariableSpec, value: Any) -> Any:
    if spec.type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise DeclarationError(f"variable {spec.name!r} is not a boolean: {value!r}")
    if spec.type == "enum":
        domain = spec.domain or ()
        if value not in domain:
            raise DeclarationError(f"variable {spec.name!r} value {value!r} not in domain {list(domain)}")
    return value


def resolve_variables(
    specs: Sequence[VariableSpec],
    *,
    flags: Mapping[str, Any],
    declaration: Mapping[str, Any],
    env: Mapping[str, Any],
    autodetect: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve declared variables by §5.2 precedence: flags > declaration > env > autodetect.

    Fails closed (§2.7): a missing *required* variable raises, naming the
    variable. Enum values are validated against their declared domain (§6.6).
    """
    resolved: dict[str, Any] = {}
    for spec in specs:
        for source in (flags, declaration, env, autodetect):
            if spec.name in source:
                resolved[spec.name] = _coerce(spec, source[spec.name])
                break
        else:
            if spec.required and spec.default is None:
                raise DeclarationError(
                    f"required variable {spec.name!r} is unset; set it via flag, declaration, "
                    f"environment, or auto-detection"
                )
            resolved[spec.name] = _coerce(spec, spec.default) if spec.default is not None else None
    return resolved


def writeback_variables(specs: Sequence[VariableSpec], resolved: Mapping[str, Any]) -> dict[str, Any]:
    """Return the subset of ``resolved`` persistable to the declaration (§5.2, §6.6).

    A ``secret``-typed variable must never be written into the declaration; its
    presence in the resolved set is a hard error (§8.15).
    """
    # §8.15: refuse to persist a secret that actually carries a VALUE. resolve_variables
    # emits a key for every spec (an unset optional resolves to None), so keying on mere
    # presence would hard-error onboarding for any profile that merely DECLARES a secret
    # variable, even when no secret value exists. A None-valued secret is never written
    # (filtered below) and is not an offence.
    secret_names = {spec.name for spec in specs if spec.secret}
    offending = {name for name in secret_names if resolved.get(name) is not None}
    if offending:
        raise DeclarationError(
            f"refusing to persist secret-typed variable(s) into the declaration: {sorted(offending)} (§8.15)"
        )
    return {name: value for name, value in resolved.items() if value is not None}
