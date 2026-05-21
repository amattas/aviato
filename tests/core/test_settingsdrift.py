from __future__ import annotations

from aviato.core.settingsdrift import classify_settings


def test_new_constraint_is_additive() -> None:
    diff = classify_settings(desired={"require_pr": True}, live={})
    assert diff.destructive is False
    assert diff.changes["require_pr"] == "additive"


def test_weakening_a_value_is_destructive() -> None:
    diff = classify_settings(desired={"required_reviews": 1}, live={"required_reviews": 2})
    assert diff.destructive is True
    assert diff.changes["required_reviews"] == "destructive"


def test_strengthening_a_value_is_additive() -> None:
    diff = classify_settings(desired={"required_reviews": 2}, live={"required_reviews": 1})
    assert diff.changes["required_reviews"] == "additive"


def test_removing_a_protection_is_destructive() -> None:
    diff = classify_settings(desired={}, live={"require_pr": True})
    assert diff.destructive is True


def test_disabling_a_boolean_protection_is_destructive() -> None:
    diff = classify_settings(desired={"require_pr": False}, live={"require_pr": True})
    assert diff.changes["require_pr"] == "destructive"


def test_no_change_is_empty_and_not_destructive() -> None:
    diff = classify_settings(desired={"x": 1}, live={"x": 1})
    assert diff.changes == {}
    assert diff.destructive is False


def test_ambiguous_change_is_destructive() -> None:
    diff = classify_settings(desired={"x": ["a"]}, live={"x": ["b"]})
    assert diff.changes["x"] == "destructive"
