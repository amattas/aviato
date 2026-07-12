from __future__ import annotations

from pathlib import Path

import pytest

from aviato.cli import main


def _consumer(tmp_path: Path) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(
        "profile: python-library\nversion: v0\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    return tmp_path


def _invalid_consumer(tmp_path: Path) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(
        "profile: node-service\nversion: v0\nvariables:\n"
        "  project-name: sample\n  language-variant: ruby\n",
        encoding="utf-8",
    )
    return tmp_path


def test_sync_materializes_managed_and_seed_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["sync", str(_consumer(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0
    assert "wrote .editorconfig" in out
    assert "seeded LICENSE" in out
    assert (tmp_path / "ruff.toml").read_text().startswith("# aviato:managed profile=python-library version=v0")


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


@pytest.mark.parametrize("command", ["sync", "doctor"])
def test_materialization_commands_reject_invalid_declared_enum_before_writes(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = _invalid_consumer(tmp_path)
    before = {path.relative_to(consumer) for path in consumer.rglob("*")}

    rc = main([command, str(consumer), *(["--no-remote-probe"] if command == "doctor" else [])])

    captured = capsys.readouterr()
    assert rc == 2
    assert "language-variant" in captured.err
    assert {path.relative_to(consumer) for path in consumer.rglob("*")} == before
