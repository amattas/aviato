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
    result = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise CommandError(command, result.returncode, result.stderr)
    return result
