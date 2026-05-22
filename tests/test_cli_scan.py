from __future__ import annotations

from pathlib import Path

import pytest

from aviato.cli import main


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
