from __future__ import annotations

import pytest

from aviato.core.errors import CompatibilityError
from aviato.core.version import is_compatible, parse_version


def test_parse_tolerates_leading_v() -> None:
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.2.3") == (1, 2, 3)


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
