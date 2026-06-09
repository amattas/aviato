from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import DeclarationError
from .version import is_known_version_pin


@dataclass
class Declaration:
    """A Consumer's ``.github/aviato.yaml`` (§6.1) — the only Library↔Consumer interface."""

    profile: str
    version: str
    docs: bool = False
    bootstrap: bool = False
    variables: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)


def _as_bool(value: object, field_name: str, path: Path) -> bool:
    """Strictly coerce a declared boolean field (§6.1, review #3).

    YAML parses an UNQUOTED ``docs: false`` as the bool ``False`` already; the bug is a QUOTED
    ``docs: "false"`` (a string), which ``bool(...)`` would render truthy → silently enable docs /
    mark a repo bootstrap. Accept only a real bool or the case-insensitive strings ``true``/
    ``false`` (a quoted value is tolerated but read by VALUE); anything else fails loud.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise DeclarationError(f"declaration field {field_name!r} must be a boolean (true/false), got {value!r}: {path}")


_KNOWN_DECLARATION_KEYS = frozenset({"profile", "version", "docs", "bootstrap", "variables", "overrides"})


def load_declaration(path: Path) -> Declaration:
    # R1-1: a corrupt/truncated/merge-conflicted declaration must surface as a DeclarationError
    # (an AviatoError) — NOT a raw yaml.YAMLError/OSError that escapes the per-repo guard in
    # scan_fleet (which catches only AviatoError) and aborts an operator's whole fleet scan (§5.11).
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise DeclarationError(f"declaration is not valid YAML: {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        # R5-4-DECL: PyYAML reading a text-mode handle propagates UnicodeDecodeError (a ValueError,
        # NOT an OSError or YAMLError) raw on a non-UTF-8 file. Without this it escapes scan_fleet's
        # `except AviatoError` guard and aborts the operator's WHOLE fleet scan (§5.11) — and leaks a
        # raw traceback in every single-repo command. Map it to a clean DeclarationError like the rest.
        raise DeclarationError(f"declaration is not valid UTF-8: {path}: {exc}") from exc
    except OSError as exc:
        raise DeclarationError(f"could not read declaration: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DeclarationError(f"declaration is not a mapping: {path}")
    # R1-9/§6.1: the declaration schema is explicit — an unknown top-level key is almost always a
    # typo (e.g. `doc:` for `docs:`) that would silently disable a feature. Reject it, never ignore.
    unknown = set(data) - _KNOWN_DECLARATION_KEYS
    if unknown:
        raise DeclarationError(
            f"declaration has unknown field(s) {sorted(unknown)} in {path}; allowed: "
            f"{sorted(_KNOWN_DECLARATION_KEYS)} (check for a typo)"
        )
    for required in ("profile", "version"):
        if required not in data:
            raise DeclarationError(f"declaration missing required field {required!r}: {path}")
    # §6.1 (review #3): an UNQUOTED `version: 1.10` is parsed by YAML as the float 1.1 — a SILENT
    # corruption (1.10 != 1.1) that would otherwise be `str()`'d and stamped into managed markers
    # and the workflow `@ref`. Reject a float outright with a quote-it hint, and require the value
    # to be a recognized pin so `version: 1.0` (malformed 2-component) / `version:` (null→'None')
    # fail loud at load instead of surfacing later as a confusing compatibility error.
    raw_version = data["version"]
    if isinstance(raw_version, float):
        raise DeclarationError(
            f"version must be a quoted string in {path}: YAML parsed it as the number "
            f"{raw_version!r} (e.g. `version: 1.10` becomes {raw_version!r}) — quote it: "
            f"`version: '{raw_version}'` (or the intended pin like '1.10.0')"
        )
    version = str(raw_version)
    if not is_known_version_pin(version):
        raise DeclarationError(
            f"version {version!r} is not a recognized pin in {path}: expected an exact 'X.Y.Z' "
            f"or a floating major 'N' (a legacy 'v' prefix is tolerated)"
        )
    for field_name in ("variables", "overrides"):
        value = data.get(field_name)
        if value is not None and not isinstance(value, dict):
            raise DeclarationError(
                f"declaration field {field_name!r} must be a mapping, got {type(value).__name__}: {path}"
            )
    return Declaration(
        profile=str(data["profile"]),
        version=version,
        docs=_as_bool(data.get("docs", False), "docs", path),
        bootstrap=_as_bool(data.get("bootstrap", False), "bootstrap", path),
        # `or {}`: a bare `variables:` / `overrides:` key (no entries) loads as None,
        # which the isinstance guard above tolerates — dict(None) must not crash.
        variables=dict(data.get("variables") or {}),
        overrides=dict(data.get("overrides") or {}),
    )


def _canonical_version(value: str) -> str:
    """Strip a legacy leading ``v`` so it is NEVER emitted (§6.1).

    Bare SemVer (``X.Y.Z`` / floating ``X``) is canonical; a leading ``v`` is tolerated on
    read but stripped on the way out, so the declaration type self-enforces the §6.1 "never
    emitted" invariant regardless of how a caller constructed it (not only via the CLI's
    normalize_pin). Only a ``v`` directly preceding a digit is the legacy pin form; anything
    else is left untouched.
    """
    return value[1:] if len(value) > 1 and value[0] == "v" and value[1].isdigit() else value


def declaration_to_yaml(declaration: Declaration) -> str:
    """Serialize a declaration to its ``.github/aviato.yaml`` text (§6.1)."""
    payload: dict[str, Any] = {
        "profile": declaration.profile,
        "version": _canonical_version(declaration.version),
        "docs": declaration.docs,
    }
    # Only the Library's own declaration carries bootstrap: true (§5.10); a normal Consumer
    # declaration omits it entirely so the field never appears as noise on adopted repos.
    if declaration.bootstrap:
        payload["bootstrap"] = True
    if declaration.variables:
        payload["variables"] = declaration.variables
    if declaration.overrides:
        payload["overrides"] = declaration.overrides
    return yaml.safe_dump(payload, sort_keys=False)


def dump_declaration(declaration: Declaration, path: Path) -> None:
    Path(path).write_text(declaration_to_yaml(declaration), encoding="utf-8")
