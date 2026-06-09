from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

# finding 10: every gh/git interaction flows through run(); without a bound, one hung
# network call stalls the operator CLI indefinitely (or burns a CI job until ITS
# timeout, default 6h). Generous default — full-history clones of large consumer
# repos are legitimate — but finite. Callers with a known-long operation may widen
# it per-call; None disables.
DEFAULT_TIMEOUT_SECONDS = 600.0


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
    timeout: float | None = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        # finding 10: a hang is an environment/network failure, not a bug — map it to
        # CommandError (exit 124, the coreutils timeout convention) so allow_error
        # paths degrade and gate paths fail loud, exactly like any other failure.
        raise CommandError(command, 124, f"timed out after {timeout}s: {exc}") from exc
    except OSError as exc:
        # R2-4-4: a missing binary (`gh`/`git` not on PATH → FileNotFoundError) or other launch
        # failure is an operator-environment error, not a bug — surface it as a CommandError so the
        # CLI's top-level handler prints a clean message + exit 2, never a raw traceback (§2.4).
        raise CommandError(command, 127, f"could not execute {command[0]!r}: {exc}") from exc
    if check and result.returncode != 0:
        raise CommandError(command, result.returncode, result.stderr)
    return result
