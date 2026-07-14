from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aviato import cli
from aviato.core.errors import AviatoError
from aviato.core.transition import (
    TransitionChange,
    build_transition_plan,
    execute_transition,
    inspect_transition,
)


def test_recovery_cli_inspects_then_requires_journal_id_to_resume_or_rollback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    plan = build_transition_plan(
        tmp_path,
        snapshot_sha="a" * 40,
        declaration_identity="id",
        changes=(TransitionChange.write("managed.txt", b"desired\n", category="managed"),),
        allow_dirty=True,
    )
    with pytest.raises(KeyboardInterrupt):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(KeyboardInterrupt) if phase == "prepared_fsync" else None
            ),
        )
    journal_id = inspect_transition(tmp_path).journal_id

    assert cli.main(["recover-transition", str(tmp_path)]) == 1
    inspection = capsys.readouterr()
    assert journal_id in inspection.out
    assert "indeterminate" in inspection.out

    assert cli.main(["recover-transition", str(tmp_path), "--resume"]) == 2
    assert f"--confirm {journal_id}" in capsys.readouterr().err
    assert cli.main(["recover-transition", str(tmp_path), "--resume", "--confirm", journal_id]) == 0
    assert (tmp_path / "managed.txt").read_bytes() == b"desired\n"
    assert not inspect_transition(tmp_path).pending


def test_ordinary_mutation_refuses_a_pending_transition(tmp_path: Path) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    plan = build_transition_plan(
        tmp_path,
        snapshot_sha="a" * 40,
        declaration_identity="id",
        changes=(TransitionChange.write("managed.txt", b"desired\n", category="managed"),),
        allow_dirty=True,
    )
    with pytest.raises(KeyboardInterrupt):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(KeyboardInterrupt) if phase == "prepared_fsync" else None
            ),
        )

    with pytest.raises(AviatoError, match="recover-transition"):
        cli._require_no_pending_transition(tmp_path)
