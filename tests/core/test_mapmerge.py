from __future__ import annotations

from aviato.core.mapmerge import deep_merge


def test_leaf_override_keeps_sibling_keys() -> None:
    base = {"x": 1, "y": 2, "nested": {"a": 1, "b": 2}}
    override = {"y": 3, "nested": {"b": 9}}
    assert deep_merge(base, override) == {"x": 1, "y": 3, "nested": {"a": 1, "b": 9}}


def test_override_replaces_non_dict_leaf() -> None:
    assert deep_merge({"k": [1, 2]}, {"k": [3]}) == {"k": [3]}


def test_override_replaces_dict_with_scalar() -> None:
    assert deep_merge({"k": {"a": 1}}, {"k": 5}) == {"k": 5}


def test_new_keys_are_added() -> None:
    assert deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_inputs_not_mutated() -> None:
    base = {"n": {"a": 1}}
    override = {"n": {"b": 2}}
    deep_merge(base, override)
    assert base == {"n": {"a": 1}}
    assert override == {"n": {"b": 2}}
