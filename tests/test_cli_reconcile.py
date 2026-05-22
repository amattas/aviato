from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aviato import __version__, cli
from aviato.cli import _desired_settings, main
from aviato.core.composition import resolve_profile
from aviato.core.ports import Issue
from aviato.core.registry import Registry
from aviato.core.settings_drift_flow import diff_identity
from aviato.core.settingsdrift import classify_settings
from aviato.paths import MODULE_SOURCE_ROOT


class _FakePlatform:
    """Minimal platform recording mutations, for the reconcile CLI glue."""

    def __init__(self, *, settings: dict[str, Any], issue: Issue | None) -> None:
        self.settings = settings
        self.issue = issue
        self.applied: list[dict[str, Any]] = []

    def read_settings(self, repo: str) -> dict[str, Any]:
        return dict(self.settings)

    def get_issue(self, repo: str, key: str) -> Issue | None:
        return self.issue

    def apply_settings(self, repo: str, payload: dict[str, Any]) -> None:
        self.applied.append(payload)

    def comment_issue(self, repo: str, key: str, body: str) -> None:
        pass


def _consumer(tmp_path: Path) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    # Pin == tool version so the §2.6 gate is satisfied without --override-version-pin.
    (github / "aviato.yaml").write_text(f"profile: python-library\nversion: {__version__}\n", encoding="utf-8")
    return tmp_path


def _current_diff_id(live: dict[str, Any]) -> str:
    desired = _desired_settings(resolve_profile(Registry(MODULE_SOURCE_ROOT), "python-library"))
    return diff_identity(classify_settings(desired=desired, live=live))


def _wire(monkeypatch: pytest.MonkeyPatch, platform: _FakePlatform) -> None:
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:o/r.git")
    monkeypatch.setattr(cli, "normalize_slug", lambda remote: "o/r")
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: platform)


def test_reconcile_stale_confirm_aborts_without_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _consumer(tmp_path)
    live: dict[str, Any] = {}  # empty live => real drift vs the desired baseline
    issue = Issue(
        key="drift",
        open=True,
        consent_diff_id=_current_diff_id(live),
        consent_actor_type="User",
        consent_role="admin",
        consent_role_lookup_ok=True,
    )
    platform = _FakePlatform(settings=live, issue=issue)
    _wire(monkeypatch, platform)

    rc = main(["reconcile", str(root), "drift", "--confirm", "0000deadbeef0000"])
    assert rc == 1  # abort/refuse maps to non-zero
    assert platform.applied == []  # the safety guarantee: no write on a stale confirm


def test_reconcile_matching_confirm_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _consumer(tmp_path)
    live: dict[str, Any] = {}
    current_id = _current_diff_id(live)
    issue = Issue(
        key="drift",
        open=True,
        consent_diff_id=current_id,
        consent_actor_type="User",
        consent_role="admin",
        consent_role_lookup_ok=True,
    )
    platform = _FakePlatform(settings=live, issue=issue)
    _wire(monkeypatch, platform)

    rc = main(["reconcile", str(root), "drift", "--confirm", current_id])
    assert rc == 0
    assert platform.applied, "a confirmed, consented, in-version reconcile must apply"


def test_reconcile_missing_declaration_errors(tmp_path: Path) -> None:
    rc = main(["reconcile", str(tmp_path), "drift", "--confirm", "x"])
    assert rc == 2
