from __future__ import annotations

import pytest

from aviato.core.errors import DeclarationError
from aviato.core.render import render


def test_substitutes_double_brace_variables() -> None:
    assert render("Copyright {{ year }} {{ owner }}", {"year": "2026", "owner": "Acme"}) == ("Copyright 2026 Acme")


def test_tolerates_whitespace_variations() -> None:
    assert render("{{name}} {{  name  }}", {"name": "x"}) == "x x"


def test_body_without_placeholders_is_unchanged() -> None:
    assert render("plain body\n", {"unused": "v"}) == "plain body\n"


def test_missing_variable_is_hard_error() -> None:
    with pytest.raises(DeclarationError):
        render("{{ missing }}", {})
