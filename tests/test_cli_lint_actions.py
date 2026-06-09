import argparse

from aviato.cli import cmd_lint_actions


def test_lint_actions_fails_closed_when_zizmor_missing(tmp_path, monkeypatch):
    """A missing zizmor must surface as a violation + non-zero exit, never a silent clean pass.

    Fail-closed (§5.14): an unrunnable pin gate reads as broken. action_pin_violations appends a
    "zizmor unavailable" row, so cmd_lint_actions returns 1.
    """
    from aviato.plugins import zizmor_scan

    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: False)
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push\n", encoding="utf-8")
    rc = cmd_lint_actions(argparse.Namespace(path=str(tmp_path)))
    assert rc == 1


def test_lint_actions_clean_repo_exits_zero(tmp_path, monkeypatch):
    from aviato.plugins import zizmor_scan

    monkeypatch.setattr(zizmor_scan, "zizmor_uses_image_violations", lambda _d: [])
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push\njobs: {}\n", encoding="utf-8")
    rc = cmd_lint_actions(argparse.Namespace(path=str(tmp_path)))
    assert rc == 0
