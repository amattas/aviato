from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aviato import __version__, cli
from aviato.cli import _desired_settings, main
from aviato.command import CommandError
from aviato.core.composition import resolve_profile
from aviato.core.consent import ACTOR_HUMAN, ROLE_PRIVILEGED
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

    def apply_settings(
        self, repo: str, payload: dict[str, Any], *, expected_live: dict[str, Any] | None = None
    ) -> None:
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
        consent_actor_type=ACTOR_HUMAN,
        consent_role=ROLE_PRIVILEGED,
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
        consent_actor_type=ACTOR_HUMAN,
        consent_role=ROLE_PRIVILEGED,
        consent_role_lookup_ok=True,
    )
    platform = _FakePlatform(settings=live, issue=issue)
    _wire(monkeypatch, platform)

    rc = main(["reconcile", str(root), "drift", "--confirm", current_id])
    assert rc == 0
    assert platform.applied, "a confirmed, consented, in-version reconcile must apply"


def test_reconcile_considers_all_markers_not_just_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # §2.6: a later marker recording a higher/incompatible version must not hide behind a
    # compatible first marker. With the old `next(iter(...))` this applied; now it refuses.
    root = _consumer(tmp_path)
    live: dict[str, Any] = {}
    current_id = _current_diff_id(live)
    issue = Issue(
        key="drift",
        open=True,
        consent_diff_id=current_id,
        consent_actor_type=ACTOR_HUMAN,
        consent_role=ROLE_PRIVILEGED,
        consent_role_lookup_ok=True,
    )
    platform = _FakePlatform(settings=live, issue=issue)
    _wire(monkeypatch, platform)
    higher_major = f"{int(__version__.split('.')[0]) + 1}.0.0"
    # First marker is compatible (== tool); a later marker records a higher major.
    monkeypatch.setattr(cli, "_recorded_versions", lambda root, expected: [__version__, higher_major])

    rc = main(["reconcile", str(root), "drift", "--confirm", current_id])
    assert rc == 1  # refused on the incompatible later marker
    assert platform.applied == []  # no mutation


def test_reconcile_missing_declaration_errors(tmp_path: Path) -> None:
    rc = main(["reconcile", str(tmp_path), "drift", "--confirm", "x"])
    assert rc == 2


def test_reconcile_apply_write_failure_is_clean_failure_not_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # §2.4/§5.7: a raw gh/git write failure during apply must surface as a clean fail-closed
    # operator error (exit 1), not an uncaught CommandError traceback.
    root = _consumer(tmp_path)
    live: dict[str, Any] = {}
    current_id = _current_diff_id(live)
    issue = Issue(
        key="drift",
        open=True,
        consent_diff_id=current_id,
        consent_actor_type=ACTOR_HUMAN,
        consent_role=ROLE_PRIVILEGED,
        consent_role_lookup_ok=True,
    )
    platform = _FakePlatform(settings=live, issue=issue)

    def _boom(repo: str, payload: dict[str, Any], *, expected_live: dict[str, Any] | None = None) -> None:
        raise CommandError(["gh", "api", "--method", "PUT", "..."], 1, "protection PUT rejected")

    platform.apply_settings = _boom  # type: ignore[method-assign]
    _wire(monkeypatch, platform)

    rc = main(["reconcile", str(root), "drift", "--confirm", current_id])
    assert rc == 1  # clean fail-closed, not a traceback
