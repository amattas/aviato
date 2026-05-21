from __future__ import annotations

import pytest

from aviato.core.errors import CompositionError
from aviato.core.listmerge import merge_list


def test_add_and_remove_preserve_set_semantics() -> None:
    assert merge_list(["a", "b"], add=["c"], remove=["a"]) == ["b", "c"]


def test_remove_absent_is_hard_error() -> None:
    with pytest.raises(CompositionError):
        merge_list(["a"], add=[], remove=["zzz"])


def test_add_duplicate_is_hard_error() -> None:
    with pytest.raises(CompositionError):
        merge_list(["a"], add=["a"], remove=[])


def test_add_and_remove_same_element_is_hard_error() -> None:
    with pytest.raises(CompositionError):
        merge_list(["a"], add=["x"], remove=["x"])


def test_result_is_deterministic_base_order_then_added() -> None:
    assert merge_list(["b", "a"], add=["c"], remove=[]) == ["b", "a", "c"]


def test_empty_add_remove_returns_base_copy() -> None:
    base = ["a", "b"]
    result = merge_list(base, add=[], remove=[])
    assert result == ["a", "b"]
    assert result is not base
