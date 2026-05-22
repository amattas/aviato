from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import DeclarationError


@dataclass
class Declaration:
    """A Consumer's ``.github/aviato.yaml`` (§6.1) — the only Library↔Consumer interface."""

    profile: str
    version: str
    docs: bool = False
    variables: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)


def load_declaration(path: Path) -> Declaration:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise DeclarationError(f"declaration is not a mapping: {path}")
    for required in ("profile", "version"):
        if required not in data:
            raise DeclarationError(f"declaration missing required field {required!r}: {path}")
    return Declaration(
        profile=str(data["profile"]),
        version=str(data["version"]),
        docs=bool(data.get("docs", False)),
        variables=dict(data.get("variables", {})),
        overrides=dict(data.get("overrides", {})),
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
    if declaration.variables:
        payload["variables"] = declaration.variables
    if declaration.overrides:
        payload["overrides"] = declaration.overrides
    return yaml.safe_dump(payload, sort_keys=False)


def dump_declaration(declaration: Declaration, path: Path) -> None:
    Path(path).write_text(declaration_to_yaml(declaration), encoding="utf-8")
