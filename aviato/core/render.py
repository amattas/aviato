from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .errors import DeclarationError

_PLACEHOLDER = re.compile(r"\{\{\s*(\w[\w-]*)\s*\}\}")


def render(body: str, variables: Mapping[str, Any], *, strict: bool = True) -> str:
    """Render a template body, substituting ``{{ name }}`` placeholders (§5.3).

    In ``strict`` mode (managed templates, re-rendered every sync) a placeholder
    with no matching variable fails loudly — no silent placeholder is left behind.
    In lenient mode (seed-once starter files the developer then owns) an unknown
    placeholder is left intact for them to fill, like a project template.
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            if strict:
                raise DeclarationError(f"template references undefined variable {name!r}")
            return match.group(0)
        return str(variables[name])

    return _PLACEHOLDER.sub(_sub, body)
