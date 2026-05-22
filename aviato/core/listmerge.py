from __future__ import annotations

from collections.abc import Sequence

from .errors import CompositionError


def merge_list(base: Sequence[str], *, add: Sequence[str], remove: Sequence[str]) -> list[str]:
    """Apply the §4.2 list semantics to ``base``.

    Children modify list-valued properties with explicit ``add``/``remove``
    only; a bare list restatement is rejected by the caller. Membership uses
    set semantics and the edge cases are hard errors:

    - ``remove`` of an absent element,
    - ``add`` of an already-present element,
    - ``add`` and ``remove`` of the same element in one layer.

    Ordering is deterministic: surviving base entries keep their order, then
    additions are appended in their given order.
    """
    add_list = list(add)
    remove_list = list(remove)

    overlap = set(add_list) & set(remove_list)
    if overlap:
        raise CompositionError(f"add and remove the same element in one layer: {sorted(overlap)}")

    base_set = set(base)
    for item in remove_list:
        if item not in base_set:
            raise CompositionError(f"remove of absent element: {item!r}")
    for item in add_list:
        if item in base_set:
            raise CompositionError(f"add of already-present element: {item!r}")

    removed = set(remove_list)
    result = [item for item in base if item not in removed]
    result.extend(add_list)
    return result
