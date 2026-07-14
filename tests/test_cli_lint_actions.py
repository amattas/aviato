from pathlib import Path
from types import SimpleNamespace

import pytest

from aviato.cli import main
from aviato.paths import POLICY_DATA_ROOT

pytestmark = pytest.mark.usefixtures("task3_pinned_context")


def test_lint_actions_fails_closed_when_zizmor_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing zizmor must surface as a violation + non-zero exit, never a silent clean pass.

    Fail-closed (§5.14): an unrunnable pin gate reads as broken. action_pin_violations appends a
    "zizmor unavailable" row, so cmd_lint_actions returns 1.
    """
    from aviato.plugins import zizmor_scan

    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: False)
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push\n", encoding="utf-8")
    rc = main(["lint-actions", str(tmp_path), "--pin", "0"])
    assert rc == 1


def test_lint_actions_clean_repo_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from aviato.plugins import zizmor_scan

    monkeypatch.setattr(zizmor_scan, "zizmor_uses_image_violations", lambda _d, **_kwargs: [])
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push\njobs: {}\n", encoding="utf-8")
    rc = main(["lint-actions", str(tmp_path), "--pin", "0"])
    assert rc == 0


def test_lint_actions_undeclared_repository_binds_target_and_pin_in_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aviato import cli
    from aviato.plugins import actionpins

    opened: list[tuple[Path, str]] = []
    context = SimpleNamespace(policy_root=POLICY_DATA_ROOT)
    monkeypatch.setattr(
        cli,
        "_open_new_context",
        lambda root, pin: opened.append((root, pin)) or context,
    )
    monkeypatch.setattr(
        cli,
        "_open_published_snapshot",
        lambda _pin: pytest.fail("target-bearing lint opened a bare snapshot"),
    )
    monkeypatch.setattr(actionpins, "action_pin_violations", lambda *_args, **_kwargs: [])

    assert main(["lint-actions", str(tmp_path), "--pin", "0"]) == 0
    assert opened == [(tmp_path.resolve(), "0")]
