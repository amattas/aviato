from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from .errors import DeclarationError
from .model import PartialVariableResolution, Unknown, UnknownValue, VariableSpec, VariableValue

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}
_YAML_SCALAR_TYPES = (str, bool, int, float, date, datetime, bytes)


def _string_scalar(spec: VariableSpec, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, _YAML_SCALAR_TYPES):
        raise DeclarationError(f"variable {spec.name!r} must be a scalar value, got {type(value).__name__}")
    return str(value)


def _coerce(spec: VariableSpec, value: Any) -> VariableValue:
    if spec.type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        if spec.secret:
            raise DeclarationError(f"variable {spec.name!r} has an invalid secret boolean value")
        raise DeclarationError(f"variable {spec.name!r} is not a boolean: {value!r}")
    if spec.type == "enum":
        domain = spec.domain or ()
        canonical = _string_scalar(spec, value)
        if canonical not in domain:
            if spec.secret:
                raise DeclarationError(f"variable {spec.name!r} has a secret value outside its declared domain")
            raise DeclarationError(f"variable {spec.name!r} value {canonical!r} not in domain {list(domain)}")
        return canonical
    return _string_scalar(spec, value)


def _coerce_supplied(spec: VariableSpec, value: Any) -> VariableValue:
    """Coerce one supplied value and keep required values complete."""

    coerced = _coerce(spec, value)
    if coerced is None and spec.required:
        raise DeclarationError(f"required variable {spec.name!r} cannot be null")
    return coerced


def _validate_source_keys(
    specs: Sequence[VariableSpec],
    sources: Sequence[tuple[str, Mapping[str, Any]]],
) -> None:
    """Reject every undeclared source key before precedence or coercion."""

    known_names = {spec.name for spec in specs}
    unknown_by_source = {
        source_name: sorted(set(source) - known_names) for source_name, source in sources if set(source) - known_names
    }
    if unknown_by_source:
        details = "; ".join(
            f"{source_name}={unknown_names}" for source_name, unknown_names in unknown_by_source.items()
        )
        raise DeclarationError(f"unknown variable key(s): {details}")


def _sources(
    *,
    flags: Mapping[str, Any],
    declaration: Mapping[str, Any],
    env: Mapping[str, Any],
    autodetect: Mapping[str, Any],
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    return (
        ("flags", flags),
        ("declaration", declaration),
        ("environment", env),
        ("auto-detection", autodetect),
    )


def resolve_variables(
    specs: Sequence[VariableSpec],
    *,
    flags: Mapping[str, Any],
    declaration: Mapping[str, Any],
    env: Mapping[str, Any],
    autodetect: Mapping[str, Any],
) -> dict[str, VariableValue]:
    """Resolve declared variables by §5.2 precedence: flags > declaration > env > autodetect.

    Fails closed (§2.7): a missing *required* variable raises, naming the
    variable. Enum values are validated against their declared domain (§6.6).
    """
    named_sources = _sources(flags=flags, declaration=declaration, env=env, autodetect=autodetect)
    _validate_source_keys(specs, named_sources)
    resolved: dict[str, VariableValue] = {}
    for spec in specs:
        for _, source in named_sources:
            if spec.name in source:
                resolved[spec.name] = _coerce_supplied(spec, source[spec.name])
                break
        else:
            if spec.required and spec.default is None:
                raise DeclarationError(
                    f"required variable {spec.name!r} is unset; set it via flag, declaration, "
                    f"environment, or auto-detection"
                )
            resolved[spec.name] = _coerce(spec, spec.default) if spec.default is not None else None
    return resolved


def resolve_partial_variables(
    specs: Sequence[VariableSpec],
    *,
    flags: Mapping[str, Any],
    declaration: Mapping[str, Any],
    env: Mapping[str, Any],
    autodetect: Mapping[str, Any],
) -> PartialVariableResolution:
    """Resolve known preview inputs while preserving absent values as ``Unknown``.

    The same closed-key and coercion rules as exact resolution apply, but missing
    values without declared defaults do not make a read-only preview fail.
    """

    named_sources = _sources(flags=flags, declaration=declaration, env=env, autodetect=autodetect)
    _validate_source_keys(specs, named_sources)
    values: dict[str, VariableValue | UnknownValue] = {}
    missing: list[str] = []
    for spec in specs:
        for _, source in named_sources:
            if spec.name in source:
                values[spec.name] = _coerce_supplied(spec, source[spec.name])
                break
        else:
            if spec.default is not None:
                values[spec.name] = _coerce(spec, spec.default)
            else:
                values[spec.name] = Unknown
                missing.append(spec.name)
    return PartialVariableResolution(values=values, missing=tuple(missing))


def resolve_declared_variables(specs: Sequence[VariableSpec], values: Mapping[str, Any]) -> dict[str, VariableValue]:
    """Validate and resolve the declaration tier through the trusted resolver.

    Declaration mappings are closed over the profile's variable specifications:
    unknown names are rejected before any value resolution. The existing
    :func:`resolve_variables` path remains the single implementation of defaulting,
    required-value checks, and type coercion. Secret-typed declarations may be
    present only with an unset (``None``) value; concrete secret values must never
    enter materialization or diagnosis.
    """
    known_names = {spec.name for spec in specs}
    unknown_names = set(values) - known_names
    if unknown_names:
        raise DeclarationError(f"unknown declaration variable(s): {sorted(unknown_names)}")

    # Refuse concrete declaration secrets before type coercion can embed their raw
    # values in a boolean/enum diagnostic. The established refusal names only the
    # offending variable(s), never their values (§8.15).
    raw_secret_names = {spec.name for spec in specs if spec.secret}
    raw_offending = {name for name in raw_secret_names if values.get(name) is not None}
    if raw_offending:
        raise DeclarationError(
            f"secret-typed variable(s) may not be set in the declaration: {sorted(raw_offending)} (§8.15)"
        )

    # Validate explicitly supplied values before checking unrelated required values.
    # This keeps the operator-facing failure anchored to the malformed declaration
    # entry while still delegating all coercion/default/required logic to one resolver.
    ordered_specs = tuple(spec for spec in specs if spec.name in values) + tuple(
        spec for spec in specs if spec.name not in values
    )
    resolved = resolve_variables(ordered_specs, flags={}, declaration=values, env={}, autodetect={})
    secret_names = raw_secret_names
    offending = {name for name in secret_names if resolved.get(name) is not None}
    if offending:
        raise DeclarationError(
            f"secret-typed variable(s) may not be set in the declaration: {sorted(offending)} (§8.15)"
        )
    return resolved


def writeback_variables(specs: Sequence[VariableSpec], resolved: Mapping[str, Any]) -> dict[str, Any]:
    """Return the subset of ``resolved`` persistable to the declaration (§5.2, §6.6).

    A ``secret``-typed variable must never be written into the declaration; its
    presence in the resolved set is a hard error (§8.15).

    CONTRACT (finding 17): the §8.15 guard is TYPE/NAME-based — it blocks variables
    *declared* ``secret: true`` (here, and in the render path's secret-name filter).
    It does NOT content-inspect values: a token pasted into a plain ``string``
    variable or into ``overrides`` persists undetected. That residual is within the
    consumer's own trust boundary and is documented in the threat model rather than
    heuristically guessed at.
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
