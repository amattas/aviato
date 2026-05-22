from __future__ import annotations

from pathlib import Path

import pytest

from aviato import cli


class FakePlatform:
    def __init__(self, *, settings=None):
        self.settings = settings or {}
        self.calls: list[tuple] = []

    def read_settings(self, repo):
        return dict(self.settings)

    def get_issue(self, repo, key):
        return None

    def open_or_update_issue(self, repo, key, title, body):
        self.calls.append(("open_or_update_issue", (repo, key, title, body)))
        return key

    def comment_issue(self, repo, key, body):
        self.calls.append(("comment_issue", (repo, key, body)))

    def open_or_update_proposal(self, repo, branch, title, files, body):
        self.calls.append(("open_or_update_proposal", (repo, branch, title, files, body)))
        return branch

    def apply_settings(self, repo, payload):
        self.calls.append(("apply_settings", (repo, payload)))

    def call_names(self):
        return [name for name, _ in self.calls]


def _consumer(tmp_path: Path) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: v0\n", encoding="utf-8")
    return tmp_path


def test_drift_report_proposes_missing_files_and_reports_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = _consumer(tmp_path)
    fake = FakePlatform(settings={"required_reviews": 1})

    monkeypatch.setattr(cli, "GitHubPlatform", lambda workdir=None: fake)
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:owner/repo.git")

    rc = cli.main(["drift-report", str(consumer)])
    out = capsys.readouterr().out
    assert rc == 0
    # nothing scaffolded yet → managed files are "missing" and get proposed
    assert "open_or_update_proposal" in fake.call_names()
    assert "proposed=" in out
    # the proposed files carry the managed marker (so a merged PR is not dirty-drift)
    _, args = next(c for c in fake.calls if c[0] == "open_or_update_proposal")
    files = args[3]
    assert files, "proposal had no files"
    assert all("aviato:managed" in body for body in files.values())
    # settings drift reported (never applied)
    assert "apply_settings" not in fake.call_names()


def test_drift_report_requires_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer = _consumer(tmp_path)
    monkeypatch.setattr(cli, "remote_url", lambda root: "")
    assert cli.main(["drift-report", str(consumer)]) != 0


def test_drift_report_skips_settings_when_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # §5.6/§2.7: the scheduled platform token cannot read branch protection (no admin). A
    # settings-read failure must NOT crash the run nor be read as "unprotected" — file
    # drift still runs, settings drift is skipped (fail-closed), and the run exits 0.
    from aviato.github import GitHubAPIError

    consumer = _consumer(tmp_path)

    class NoAdminPlatform(FakePlatform):
        def read_settings(self, repo):
            raise GitHubAPIError(f"repos/{repo}/branches/main/protection", 1, "HTTP 403: Forbidden")

    fake = NoAdminPlatform()
    monkeypatch.setattr(cli, "GitHubPlatform", lambda workdir=None: fake)
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:owner/repo.git")

    rc = cli.main(["drift-report", str(consumer)])
    captured = capsys.readouterr()
    assert rc == 0  # did not crash
    assert "open_or_update_proposal" in fake.call_names()  # file drift still ran
    assert "settings drift: skipped" in captured.err
    assert "apply_settings" not in fake.call_names()  # never mutates
