from __future__ import annotations

from collections.abc import Sequence

from .errors import CompositionError


def _first_duplicate(values: Sequence[str]) -> str | None:
    """The first element that appears more than once in ``values``, or ``None``."""
    seen: set[str] = set()
    for item in values:
        if item in seen:
            return item
        seen.add(item)
    return None


def merge_list(base: Sequence[str], *, add: Sequence[str], remove: Sequence[str]) -> list[str]:
    """Apply the §4.2 list semantics to ``base``.

    Children modify list-valued properties with explicit ``add``/``remove``
    only; a bare list restatement is rejected by the caller. Membership uses
    **set semantics — no duplicates** — and the edge cases are hard errors:

    - ``remove`` of an absent element,
    - ``add`` of an already-present element,
    - ``add`` and ``remove`` of the same element in one layer,
    - a **duplicate within** the ``add`` or ``remove`` list (redundant/conflicting
      intent, the same class §4.2 makes an error for add-already-present),
    - a **duplicate in the base** itself (the resolved set must already obey set
      semantics; a duplicate signals malformed bundle data, fail loud).

    Ordering is deterministic: surviving base entries keep their order, then
    additions are appended in their given order.
    """
    add_list = list(add)
    remove_list = list(remove)

    # Set semantics (§4.2): the resolved base and each operation list must be
    # duplicate-free. A duplicate is the same "redundant or conflicting intent"
    # that add-already-present is — never a silent dedup.
    base_dup = _first_duplicate(base)
    if base_dup is not None:
        raise CompositionError(f"base list contains a duplicate (violates set semantics §4.2): {base_dup!r}")
    add_dup = _first_duplicate(add_list)
    if add_dup is not None:
        raise CompositionError(f"add lists the same element twice: {add_dup!r}")
    remove_dup = _first_duplicate(remove_list)
    if remove_dup is not None:
        raise CompositionError(f"remove lists the same element twice: {remove_dup!r}")

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
