"""findings 10/30: subprocess timeout mapping and bounded gh rate-limit retry."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from aviato import command, github
from aviato.command import DEFAULT_TIMEOUT_SECONDS, CommandError, run
from aviato.core.errors import InventoryError
from aviato.repos import git_candidate_paths


def test_run_maps_timeout_to_command_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        timeout = kwargs.get("timeout")
        assert isinstance(timeout, (int, float))
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(CommandError) as exc_info:
        run(["gh", "api", "x"], timeout=1)
    assert exc_info.value.returncode == 124
    assert "timed out" in str(exc_info.value)


def test_run_passes_a_finite_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run(["echo", "hi"])
    assert seen["timeout"] == DEFAULT_TIMEOUT_SECONDS
    assert DEFAULT_TIMEOUT_SECONDS is not None


def test_marker_scan_is_nul_safe_and_git_failures_map_to_aviato_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"ordinary.txt\0line\nbreak.yml\0nonutf8-\xff.yml\0"
    monkeypatch.setattr(
        "aviato.repos.run_bytes",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, payload, b""),
    )
    assert git_candidate_paths(tmp_path) == (
        "ordinary.txt",
        "line\nbreak.yml",
        "nonutf8-\udcff.yml",
    )

    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise CommandError(["git"], 127, "missing git")

    monkeypatch.setattr("aviato.repos.run_bytes", fail)
    with pytest.raises(InventoryError, match="could not enumerate repository files"):
        git_candidate_paths(tmp_path)


def test_gh_read_retries_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    responses = [
        subprocess.CompletedProcess([], 1, "", "HTTP 429: API rate limit exceeded"),
        subprocess.CompletedProcess([], 0, '{"ok": true}', ""),
    ]

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return responses[len(calls) - 1]

    monkeypatch.setattr(github, "run", fake_run)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert github.gh_json("repos/o/r") == {"ok": True}
    assert len(calls) == 2


def test_gh_read_does_not_retry_plain_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # Auth/404/semantic errors must surface immediately — only throttle shapes retry.
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess([], 1, "", "gh: Not Found (HTTP 404)")

    monkeypatch.setattr(github, "run", fake_run)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(github.GitHubAPIError):
        github.gh_json("repos/o/r")
    assert len(calls) == 1


def test_gh_read_gives_up_after_bounded_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess([], 1, "", "you have exceeded a secondary rate limit")

    monkeypatch.setattr(github, "run", fake_run)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(github.GitHubAPIError):
        github.gh_json("repos/o/r")
    assert len(calls) == github._RATE_LIMIT_ATTEMPTS


def test_run_timeout_degrades_when_check_false(monkeypatch: pytest.MonkeyPatch) -> None:
    # second-review fix: with check=False a timeout must RETURN a failed result (like
    # any other failure) so allow_error/optional read paths degrade — one slow call
    # must not abort a whole fleet sweep.
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        timeout = kwargs.get("timeout")
        assert isinstance(timeout, (int, float))
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run(["gh", "api", "x"], check=False, timeout=1)
    assert result.returncode == 124
    assert "timed out" in result.stderr


def test_run_to_path_preserves_binary_bytes_with_a_finite_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "archive.tar.gz"
    payload = b"\x1f\x8b\x08\x00\xff\xfe\x80binary\x00"
    seen: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        stdout = kwargs["stdout"]
        assert hasattr(stdout, "write")
        cast(BinaryIO, stdout).write(payload)
        return subprocess.CompletedProcess(cmd, 0, None, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = command.run_to_path(["gh", "api", "repos/o/r/tarball/abc"], destination)

    assert result.returncode == 0
    assert destination.read_bytes() == payload
    assert seen["timeout"] == DEFAULT_TIMEOUT_SECONDS
    assert DEFAULT_TIMEOUT_SECONDS is not None
    assert seen.get("shell", False) is False


def test_run_to_path_close_error_is_typed_and_removes_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "archive.tar.gz"
    original_open = Path.open

    class CloseFailingOutput:
        def __init__(self, path: Path) -> None:
            self._output = original_open(path, "xb")

        def __enter__(self) -> CloseFailingOutput:
            return self

        def __exit__(self, *_args: object) -> None:
            self._output.close()
            raise OSError("simulated close failure")

        def write(self, payload: bytes) -> int:
            return self._output.write(payload)

        def flush(self) -> None:
            self._output.flush()

        def fileno(self) -> int:
            return self._output.fileno()

    def fake_open(path: Path, mode: str = "r", *args: object, **kwargs: object) -> CloseFailingOutput:
        assert path == destination
        assert mode == "xb"
        assert not args
        assert not kwargs
        return CloseFailingOutput(path)

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        stdout = kwargs["stdout"]
        assert hasattr(stdout, "write")
        cast(BinaryIO, stdout).write(b"partial archive")
        return subprocess.CompletedProcess(cmd, 0, None, "")

    monkeypatch.setattr(Path, "open", fake_open)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(CommandError, match="could not finalize output path") as exc_info:
        command.run_to_path(["gh", "api", "repos/o/r/tarball/abc"], destination)

    assert exc_info.value.returncode == 74
    assert not destination.exists()


def test_run_to_path_real_child_preserves_invalid_utf8_stdout(tmp_path: Path) -> None:
    destination = tmp_path / "child-output.bin"
    payload = bytes([0x00, 0xFF, 0x80, 0xFE, 0x41, 0x0A])

    result = command.run_to_path(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(bytes([0, 255, 128, 254, 65, 10]))",
        ],
        destination,
        timeout=5,
    )

    assert result.returncode == 0
    assert destination.read_bytes() == payload


def test_run_to_path_real_child_timeout_removes_partial_file(tmp_path: Path) -> None:
    destination = tmp_path / "child-output.bin"

    with pytest.raises(CommandError) as exc_info:
        command.run_to_path(
            [
                sys.executable,
                "-c",
                ("import sys, time; sys.stdout.buffer.write(b'partial'); sys.stdout.buffer.flush(); time.sleep(5)"),
            ],
            destination,
            timeout=0.5,
        )

    assert exc_info.value.returncode == 124
    assert not destination.exists()


@pytest.mark.parametrize(
    ("failure", "expected_returncode"),
    [("launch", 127), ("nonzero", 23), ("timeout", 124)],
)
def test_binary_output_failure_timeout_and_launch_error_remove_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_returncode: int,
) -> None:
    destination = tmp_path / "archive.tar.gz"

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if failure == "launch":
            raise FileNotFoundError("gh is missing")
        stdout = kwargs["stdout"]
        assert hasattr(stdout, "write")
        cast(BinaryIO, stdout).write(b"partial archive")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        return subprocess.CompletedProcess(cmd, 23, None, "download failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(CommandError) as exc_info:
        command.run_to_path(["gh", "api", "repos/o/r/tarball/abc"], destination, timeout=1)

    assert exc_info.value.returncode == expected_returncode
    assert not destination.exists()


@pytest.mark.parametrize("failure", ["nonzero", "timeout"])
def test_run_to_path_check_false_returns_failure_without_accepting_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    destination = tmp_path / "archive.tar.gz"

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        stdout = kwargs["stdout"]
        assert hasattr(stdout, "write")
        cast(BinaryIO, stdout).write(b"partial archive")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=2)
        return subprocess.CompletedProcess(cmd, 9, None, "download failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = command.run_to_path(
        ["gh", "api", "repos/o/r/tarball/abc"],
        destination,
        check=False,
        timeout=2,
    )

    assert result.returncode == (124 if failure == "timeout" else 9)
    assert not destination.exists()


def test_run_to_path_never_truncates_or_removes_a_preexisting_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "archive.tar.gz"
    original = b"caller-owned archive"
    destination.write_bytes(original)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not launch")),
    )

    with pytest.raises(CommandError, match="already exists"):
        command.run_to_path(["gh", "api", "repos/o/r/tarball/abc"], destination)

    assert destination.read_bytes() == original
