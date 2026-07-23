"""Bot repo-status probe: configured/unconfigured, covered/uncovered, and error paths."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from aviato.botstatus import BotStatus, probe_bot_status


def _opener_returning(payload: dict) -> object:
    class _Response(io.BytesIO):
        status = 200

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args):  # noqa: ANN002, ANN204
            return False

    def opener(request, timeout):  # noqa: ANN001, ANN202
        assert request.get_header("Authorization") == "Bearer tok"
        return _Response(json.dumps(payload).encode())

    return opener


def _opener_raising(exc: Exception) -> object:
    def opener(request, timeout):  # noqa: ANN001, ANN202
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
    monkeypatch: pytest.MonkeyPatch, payload: dict, expected_covered: bool, expected_last: str | None
) -> None:
    monkeypatch.setenv("AVIATO_BOT_URL", "https://bot.example")
    monkeypatch.setenv("AVIATO_BOT_STATUS_TOKEN", "tok")
    status = probe_bot_status("acme/app", opener=_opener_returning(payload))
    assert status.configured and status.covered is expected_covered
    assert status.last_checked == expected_last
    assert status.error is None


@pytest.mark.parametrize(
    ("exc", "expected_covered", "error_contains"),
    [
        (urllib.error.HTTPError("u", 404, "nf", {}, None), False, None),
        (urllib.error.HTTPError("u", 401, "bad", {}, None), None, "401"),
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
