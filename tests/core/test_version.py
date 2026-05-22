from __future__ import annotations

import pytest

from aviato.core.errors import CompatibilityError
from aviato.core.version import is_compatible, is_known_version_pin, normalize_pin, parse_version


def test_parse_tolerates_leading_v() -> None:
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.2.3") == (1, 2, 3)


def test_is_known_version_pin() -> None:
    assert is_known_version_pin("1.2.3") is True
    assert is_known_version_pin("v1.2.3") is True
    assert is_known_version_pin("1") is True
    assert is_known_version_pin("v1") is True
    assert is_known_version_pin("0") is True
    assert is_known_version_pin("garbage") is False
    assert is_known_version_pin("") is False
    assert is_known_version_pin("1.2") is False


def test_normalize_pin_strips_leading_v_and_validates() -> None:
    # Bare canonical form (§6.1): a legacy leading ``v`` is tolerated on input but
    # stripped on output, while bare pins pass through unchanged.
    assert normalize_pin("v1.2.3") == "1.2.3"
    assert normalize_pin("1.2.3") == "1.2.3"
    assert normalize_pin("v1") == "1"
    assert normalize_pin("0") == "0"
    assert normalize_pin("  v2.0.0  ") == "2.0.0"  # surrounding whitespace tolerated
    for bad in ("garbage", "", "1.2", "V1"):
        with pytest.raises(CompatibilityError):
            normalize_pin(bad)


def test_parse_rejects_garbage() -> None:
    with pytest.raises(CompatibilityError):
        parse_version("not-a-version")


def test_exact_pin_requires_major_match_and_tool_ge_recorded() -> None:
    assert is_compatible(tool="1.4.0", pinned="v1.2.0", recorded="1.2.0") is True
    assert is_compatible(tool="1.1.0", pinned="v1.2.0", recorded="1.2.0") is False  # tool < recorded
    assert is_compatible(tool="2.0.0", pinned="v1.2.0", recorded="1.2.0") is False  # major mismatch


def test_floating_major_pin_matches_on_major() -> None:
    assert is_compatible(tool="1.9.0", pinned="v1", recorded="1.3.0") is True
    assert is_compatible(tool="1.2.0", pinned="v1", recorded="1.3.0") is False  # tool < recorded
    assert is_compatible(tool="2.0.0", pinned="v1", recorded="1.3.0") is False  # major mismatch


def test_tool_equal_to_recorded_is_compatible() -> None:
    assert is_compatible(tool="1.2.0", pinned="v1", recorded="1.2.0") is True
