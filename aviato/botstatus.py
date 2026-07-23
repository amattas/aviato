"""Probe the aviato-bot repo-status endpoint (the drift-automation heartbeat, §17).

Replaces the retired scheduled-workflow heartbeat: the bot is now the drift detector,
so doctor/scan ask it directly whether a repo is covered and when drift last ran.
Read-only; stdlib-only so the CLI gains no dependency.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

BOT_URL_ENV = "AVIATO_BOT_URL"
BOT_STATUS_TOKEN_ENV = "AVIATO_BOT_STATUS_TOKEN"
_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class BotStatus:
    """The tri-state heartbeat: unconfigured, covered/uncovered, or probe failure."""

    configured: bool
    covered: bool | None  # None: unconfigured or the probe failed
    last_checked: str | None  # latest drift updated_at (ISO-8601), when covered
    error: str | None


def probe_bot_status(repo: str, *, opener: Callable[..., Any] | None = None) -> BotStatus:
    base_url = os.environ.get(BOT_URL_ENV, "").rstrip("/")
    token = os.environ.get(BOT_STATUS_TOKEN_ENV, "")
    if not base_url or not token:
        return BotStatus(configured=False, covered=None, last_checked=None, error=None)
    query = urllib.parse.urlencode({"repo": repo})
    request = urllib.request.Request(
        f"{base_url}/api/repo-status?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return BotStatus(configured=True, covered=False, last_checked=None, error=None)
        return BotStatus(
            configured=True, covered=None, last_checked=None, error=f"bot status probe failed: HTTP {exc.code}"
        )
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return BotStatus(configured=True, covered=None, last_checked=None, error=f"bot status probe failed: {exc}")
    if not isinstance(payload, dict):
        return BotStatus(
            configured=True,
            covered=None,
            last_checked=None,
            error="bot status probe failed: unexpected response body",
        )
    drift = payload.get("drift")
    timestamps: list[str] = sorted(
        row["updated_at"] for row in (drift or []) if isinstance(row, dict) and isinstance(row.get("updated_at"), str)
    )
    return BotStatus(
        configured=True,
        covered=bool(payload.get("managed")),
        last_checked=timestamps[-1] if timestamps else None,
        error=None,
    )
