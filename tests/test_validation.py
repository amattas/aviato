from __future__ import annotations

from pathlib import Path

import pytest

from aviato.paths import REPO_ROOT
from aviato.validation import validate


def test_repository_validates_clean() -> None:
    errors = validate(REPO_ROOT)
    assert errors == [], errors


def test_validate_flags_core_agnosticism_violation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Build a throwaway core dir with a denylisted token and point the check at it.
    from aviato import validation

    bad_core = tmp_path / "aviato" / "core"
    bad_core.mkdir(parents=True)
    (bad_core / "leak.py").write_text("ENGINE = 'docusaurus'\n", encoding="utf-8")
    denylist = tmp_path / "denylist.txt"
    denylist.write_text("docusaurus\n", encoding="utf-8")

    errors: list[str] = []
    validation._check_core_agnosticism(bad_core, denylist, errors)
    assert any("docusaurus" in e for e in errors)
