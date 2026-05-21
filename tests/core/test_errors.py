from __future__ import annotations

import pytest

from aviato.core.errors import (
    AuthorizationError,
    AviatoError,
    BootstrapError,
    CompatibilityError,
    CompositionError,
    DeclarationError,
    MarkerError,
)


def test_errors_subclass_base_and_exception() -> None:
    for exc in (
        CompositionError,
        DeclarationError,
        MarkerError,
        AuthorizationError,
        CompatibilityError,
        BootstrapError,
    ):
        assert issubclass(exc, AviatoError)
        assert issubclass(exc, Exception)


def test_composition_error_raises() -> None:
    with pytest.raises(CompositionError):
        raise CompositionError("boom")
