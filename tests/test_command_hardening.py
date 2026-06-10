"""findings 10/30: subprocess timeout mapping and bounded gh rate-limit retry."""

from __future__ import annotations

import subprocess

import pytest

from aviato import github
from aviato.command import DEFAULT_TIMEOUT_SECONDS, CommandError, run


def test_run_maps_timeout_to_command_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(CommandError) as exc_info:
        run(["gh", "api", "x"], timeout=1)
    assert exc_info.value.returncode == 124
    assert "timed out" in str(exc_info.value)


def test_run_passes_a_finite_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run(["echo", "hi"])
    assert seen["timeout"] == DEFAULT_TIMEOUT_SECONDS
    assert DEFAULT_TIMEOUT_SECONDS is not None


def test_gh_read_retries_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    responses = [
        subprocess.CompletedProcess([], 1, "", "HTTP 429: API rate limit exceeded"),
        subprocess.CompletedProcess([], 0, '{"ok": true}', ""),
    ]

    def fake_run(args, **kwargs):
        calls.append(args)
        return responses[len(calls) - 1]

    monkeypatch.setattr(github, "run", fake_run)
    monkeypatch.setattr(github.time, "sleep", lambda s: None)
    assert github.gh_json("repos/o/r") == {"ok": True}
    assert len(calls) == 2


def test_gh_read_does_not_retry_plain_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # Auth/404/semantic errors must surface immediately — only throttle shapes retry.
    calls: list = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess([], 1, "", "gh: Not Found (HTTP 404)")

    monkeypatch.setattr(github, "run", fake_run)
    monkeypatch.setattr(github.time, "sleep", lambda s: None)
    with pytest.raises(github.GitHubAPIError):
        github.gh_json("repos/o/r")
    assert len(calls) == 1


def test_gh_read_gives_up_after_bounded_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess([], 1, "", "you have exceeded a secondary rate limit")

    monkeypatch.setattr(github, "run", fake_run)
    monkeypatch.setattr(github.time, "sleep", lambda s: None)
    with pytest.raises(github.GitHubAPIError):
        github.gh_json("repos/o/r")
    assert len(calls) == github._RATE_LIMIT_ATTEMPTS


def test_run_timeout_degrades_when_check_false(monkeypatch: pytest.MonkeyPatch) -> None:
    # second-review fix: with check=False a timeout must RETURN a failed result (like
    # any other failure) so allow_error/optional read paths degrade — one slow call
    # must not abort a whole fleet sweep.
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run(["gh", "api", "x"], check=False, timeout=1)
    assert result.returncode == 124
    assert "timed out" in result.stderr
