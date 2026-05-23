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


def test_duplicate_within_add_list_is_hard_error() -> None:
    # §4.2 set semantics: a doubled add is redundant/conflicting intent, not a silent dedup.
    with pytest.raises(CompositionError):
        merge_list(["a"], add=["c", "c"], remove=[])


def test_duplicate_within_remove_list_is_hard_error() -> None:
    with pytest.raises(CompositionError):
        merge_list(["a", "b"], add=[], remove=["a", "a"])


def test_duplicate_in_base_is_hard_error() -> None:
    # The resolved base must already obey set semantics (§4.2); a duplicate is malformed data.
    with pytest.raises(CompositionError):
        merge_list(["a", "a"], add=["c"], remove=[])


def test_result_is_deterministic_base_order_then_added() -> None:
    assert merge_list(["b", "a"], add=["c"], remove=[]) == ["b", "a", "c"]


def test_empty_add_remove_returns_base_copy() -> None:
    base = ["a", "b"]
    result = merge_list(base, add=[], remove=[])
    assert result == ["a", "b"]
    assert result is not base
