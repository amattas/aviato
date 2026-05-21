from __future__ import annotations

from aviato.repos import normalize_slug


def test_normalize_slug_from_https_remote() -> None:
    assert normalize_slug("https://github.com/amattas/aviato.git") == "amattas/aviato"


def test_normalize_slug_from_ssh_remote() -> None:
    assert normalize_slug("git@github.com:amattas/aviato.git") == "amattas/aviato"
