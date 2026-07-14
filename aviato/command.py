from __future__ import annotations

import os
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
        # finding 10 (+ second-review fix): a hang is an environment/network failure,
        # not a bug — treat it EXACTLY like any other failure. With check=True it
        # raises CommandError (exit 124, the coreutils timeout convention); with
        # check=False it RETURNS a failed CompletedProcess so allow_error/optional
        # read paths degrade instead of one slow call aborting a whole fleet sweep.
        if check:
            raise CommandError(command, 124, f"timed out after {timeout}s: {exc}") from exc
        return subprocess.CompletedProcess(list(command), 124, "", f"timed out after {timeout}s: {exc}")
    except OSError as exc:
        # R2-4-4: a missing binary (`gh`/`git` not on PATH → FileNotFoundError) or other launch
        # failure is an operator-environment error, not a bug — surface it as a CommandError so the
        # CLI's top-level handler prints a clean message + exit 2, never a raw traceback (§2.4).
        raise CommandError(command, 127, f"could not execute {command[0]!r}: {exc}") from exc
    if check and result.returncode != 0:
        raise CommandError(command, result.returncode, result.stderr)
    return result


def run_to_path(
    command: Sequence[str],
    destination: str | Path,
    *,
    cwd: str | Path | None = None,
    check: bool = True,
    timeout: float | None = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Stream binary stdout to a new file while retaining decoded stderr.

    The destination is created exclusively. A failed launch, timeout, or nonzero
    command removes only the partial file created by this invocation; a
    pre-existing caller-owned path is never opened, truncated, or unlinked.
    """

    path = Path(destination)
    created = False
    accepted = False
    try:
        try:
            output = path.open("xb")
            created = True
        except FileExistsError as exc:
            raise CommandError(command, 73, f"destination already exists: {path}") from exc
        except OSError as exc:
            raise CommandError(command, 73, f"could not create output path {path}: {exc}") from exc

        with output:
            try:
                result = subprocess.run(
                    list(command),
                    cwd=str(cwd) if cwd is not None else None,
                    check=False,
                    text=True,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                    shell=False,
                )
            except subprocess.TimeoutExpired as exc:
                message = f"timed out after {timeout}s: {exc}"
                if check:
                    raise CommandError(command, 124, message) from exc
                return subprocess.CompletedProcess(list(command), 124, None, message)
            except OSError as exc:
                raise CommandError(command, 127, f"could not execute {command[0]!r}: {exc}") from exc

            if result.returncode != 0:
                if check:
                    raise CommandError(command, result.returncode, result.stderr)
                return result
            output.flush()
            os.fsync(output.fileno())
            accepted = True
            return result
    finally:
        if created and not accepted:
            path.unlink(missing_ok=True)
