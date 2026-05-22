from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from aviato.cli import _scan_has_file_drift, main
from aviato.core.file_drift_flow import _PROPOSABLE


def test_scan_prints_per_repo_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text("profile: python-library\nversion: v1\n", encoding="utf-8")
    plain = tmp_path / "plain"
    plain.mkdir()

    rc = main(["scan", str(consumer), str(plain)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "python-library" in out
    assert "missing" in out  # unscaffolded managed files
    assert "ERROR: no declaration" in out  # the plain repo


@pytest.mark.parametrize(
    ("status", "fixable"),
    [
        ("missing", True),
        ("mergeable-drift", True),  # regression (§5.11): body drift MUST be proposable via --fix
        ("dirty-drift", False),  # operator hand-edited / malformed marker — never auto-fixed
        ("clean", False),
    ],
)
def test_scan_fix_gate_matches_proposable_statuses(status: str, fixable: bool) -> None:
    # The --fix gate must align with file_drift_flow._PROPOSABLE; a stale "drift" literal
    # here previously made --fix silently no-op on mergeable-drift (the common drift case).
    assert _scan_has_file_drift(SimpleNamespace(statuses={"some/file": status})) is fixable


def test_scan_fix_gate_empty_is_not_fixable() -> None:
    assert _scan_has_file_drift(SimpleNamespace(statuses={})) is False


def test_scan_fix_gate_agrees_with_proposable_set() -> None:
    # The gate must agree with file_drift_flow._PROPOSABLE for EVERY status, so a future
    # proposable status added there cannot silently diverge from what --fix acts on.
    for status in (*_PROPOSABLE, "dirty-drift", "clean"):
        assert _scan_has_file_drift(SimpleNamespace(statuses={"f": status})) is (status in _PROPOSABLE)


def test_scan_fix_blocks_incompatible_version_pin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # §2.6/§5.12: scan --fix must enforce the version-pin gate like drift-report/sync —
    # an incompatible local tool cannot regenerate a consumer's files. Pin at a major the
    # 0.x tool can never satisfy, and assert --fix reports the mismatch (and does not crash).
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text("profile: python-library\nversion: 2.0.0\n", encoding="utf-8")
    rc = main(["scan", str(consumer), "--fix"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "version-pin mismatch" in err
