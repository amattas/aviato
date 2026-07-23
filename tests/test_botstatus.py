"""Bot repo-status probe: configured/unconfigured, covered/uncovered, and error paths."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import Message
from typing import Any

import pytest

from aviato.botstatus import BotStatus, probe_bot_status


def _opener_returning(payload: Any) -> Callable[..., Any]:
    class _Response(io.BytesIO):
        status = 200

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def opener(request: urllib.request.Request, timeout: float) -> _Response:
        assert request.get_header("Authorization") == "Bearer tok"
        return _Response(json.dumps(payload).encode())

    return opener


def _opener_raising(exc: Exception) -> Callable[..., Any]:
    def opener(request: urllib.request.Request, timeout: float) -> Any:
        raise exc

    return opener


def test_unconfigured_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AVIATO_BOT_URL", raising=False)
    monkeypatch.delenv("AVIATO_BOT_STATUS_TOKEN", raising=False)
    status = probe_bot_status("acme/app")
    assert status == BotStatus(configured=False, covered=None, last_checked=None, error=None)


@pytest.mark.parametrize(
    ("payload", "expected_covered", "expected_last"),
    [
        (
            {
                "managed": True,
                "repo": "acme/app",
                "drift": [
                    {"kind": "settings", "status": "clean", "detail": None, "updated_at": "2026-07-20T06:17:00+00:00"},
                    {"kind": "file", "status": "drift", "detail": None, "updated_at": "2026-07-22T06:17:00+00:00"},
                ],
            },
            True,
            "2026-07-22T06:17:00+00:00",
        ),
        ({"managed": True, "repo": "acme/app", "drift": []}, True, None),
    ],
)
def test_covered_repo_reports_latest_check(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], expected_covered: bool, expected_last: str | None
) -> None:
    monkeypatch.setenv("AVIATO_BOT_URL", "https://bot.example")
    monkeypatch.setenv("AVIATO_BOT_STATUS_TOKEN", "tok")
    status = probe_bot_status("acme/app", opener=_opener_returning(payload))
    assert status.configured and status.covered is expected_covered
    assert status.last_checked == expected_last
    assert status.error is None


def test_non_dict_body_reports_probe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AVIATO_BOT_URL", "https://bot.example")
    monkeypatch.setenv("AVIATO_BOT_STATUS_TOKEN", "tok")
    status = probe_bot_status("acme/app", opener=_opener_returning([]))
    assert status.configured
    assert status.covered is None
    assert status.last_checked is None
    assert status.error == "bot status probe failed: unexpected response body"


@pytest.mark.parametrize(
    ("exc", "expected_covered", "error_contains"),
    [
        (urllib.error.HTTPError("u", 404, "nf", Message(), None), False, None),
        (urllib.error.HTTPError("u", 401, "bad", Message(), None), None, "401"),
        (urllib.error.URLError("refused"), None, "refused"),
    ],
)
def test_error_paths(
    monkeypatch: pytest.MonkeyPatch, exc: Exception, expected_covered: bool | None, error_contains: str | None
) -> None:
    monkeypatch.setenv("AVIATO_BOT_URL", "https://bot.example")
    monkeypatch.setenv("AVIATO_BOT_STATUS_TOKEN", "tok")
    status = probe_bot_status("acme/app", opener=_opener_raising(exc))
    assert status.configured
    assert status.covered is expected_covered
    if error_contains is None:
        assert status.error is None
    else:
        assert error_contains in (status.error or "")
