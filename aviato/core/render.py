from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .errors import DeclarationError

_PLACEHOLDER = re.compile(r"\{\{\s*(\w[\w-]*)\s*\}\}")


def render(body: str, variables: Mapping[str, Any]) -> str:
    """Render a template body, substituting ``{{ name }}`` placeholders (§5.3).

    A placeholder with no matching variable fails loudly — no silent placeholder
    is left behind (§5.3 failure handling).
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise DeclarationError(f"template references undefined variable {name!r}")
        return str(variables[name])

    return _PLACEHOLDER.sub(_sub, body)
