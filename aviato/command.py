from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path


class CommandError(RuntimeError):
    def __init__(self, command: Sequence[str], returncode: int, stderr: str) -> None:
        self.command = list(command)
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"{' '.join(command)} failed with exit code {returncode}: {stderr.strip()}")


def run(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        # R2-4-4: a missing binary (`gh`/`git` not on PATH → FileNotFoundError) or other launch
        # failure is an operator-environment error, not a bug — surface it as a CommandError so the
        # CLI's top-level handler prints a clean message + exit 2, never a raw traceback (§2.4).
        raise CommandError(command, 127, f"could not execute {command[0]!r}: {exc}") from exc
    if check and result.returncode != 0:
        raise CommandError(command, result.returncode, result.stderr)
    return result
