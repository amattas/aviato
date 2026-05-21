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


def dump_declaration(declaration: Declaration, path: Path) -> None:
    payload: dict[str, Any] = {
        "profile": declaration.profile,
        "version": declaration.version,
        "docs": declaration.docs,
    }
    if declaration.variables:
        payload["variables"] = declaration.variables
    if declaration.overrides:
        payload["overrides"] = declaration.overrides
    Path(path).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
