from __future__ import annotations

from pathlib import Path

import pytest

from aviato.cli import main


def _consumer(tmp_path: Path) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: v1\n", encoding="utf-8")
    return tmp_path


def test_sync_materializes_managed_and_seed_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["sync", str(_consumer(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0
    assert "wrote .editorconfig" in out
    assert "seeded LICENSE" in out
    assert (tmp_path / "ruff.toml").read_text().startswith("# aviato:managed profile=python-library version=v1")


def test_sync_is_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    consumer = _consumer(tmp_path)
    main(["sync", str(consumer)])
    capsys.readouterr()
    rc = main(["sync", str(consumer)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "wrote " not in out  # nothing rewritten on a clean tree
    assert "unchanged .editorconfig" in out


def test_sync_without_declaration_fails(tmp_path: Path) -> None:
    assert main(["sync", str(tmp_path)]) != 0
