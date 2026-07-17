from __future__ import annotations

from pathlib import Path

import pytest

from aviato import validation
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


@pytest.mark.parametrize(
    ("policy_form", "pep440_form"),
    [
        ("0.4.0", "0.4.0"),
        ("0.4.1-alpha2", "0.4.1a2"),
        ("1.2.3-beta10", "1.2.3b10"),
    ],
)
def test_policy_version_maps_to_pep440(policy_form: str, pep440_form: str) -> None:
    # §11.6 dev-suffixed versions: pyproject carries the policy form, installed metadata the
    # PEP 440 canonical form; the parity check must compare canonically or the Library can
    # never stage a TestPyPI verification release (discovered live on PR #84).
    assert validation._policy_version_to_pep440(policy_form) == pep440_form
