from __future__ import annotations

from copy import deepcopy
from typing import Any


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``override`` onto ``base`` at the leaf (§4.2 map semantics).

    A child overriding one nested key must not drop sibling keys, so dict
    values are merged recursively. A non-dict value (or a dict replacing a
    scalar, or vice versa) replaces wholesale. Neither input is mutated.
    """
    result = deepcopy(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = deepcopy(value)
    return result
