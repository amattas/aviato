from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from aviato import cli
from aviato.core.diagnosis import diagnose
from aviato.core.ports import Issue, Platform, SettingsApplyResult
from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT


def _record_keyword_arguments[**P, R](fn: Callable[P, R], calls: list[dict[str, object]]) -> Callable[P, R]:
    def recording(*args: P.args, **kwargs: P.kwargs) -> R:
        calls.append(dict(kwargs))
        return fn(*args, **kwargs)

    return recording


class FakePlatform:
    def __init__(
        self,
        *,
        settings: dict[str, Any] | None = None,
        rulesets: list[dict[str, Any]] | None = None,
    ) -> None:
        self.settings = settings or {}
        # Default: live rulesets equal the rendered desired (no missing/drifted rulesets) so these
        # file/settings-drift tests aren't perturbed; a ruleset-drift test passes explicit payloads.
        self._rulesets = rulesets
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def read_settings(self, repo: str) -> dict[str, Any]:
        return dict(self.settings)

    def read_rulesets(self, repo: str) -> list[dict[str, Any]]:
        if self._rulesets is not None:
            return self._rulesets
        from aviato.cli import _profile_status_checks
        from aviato.rulesets import render_all_rulesets

        return render_all_rulesets(extra_status_checks=_profile_status_checks("python-library"))

    def get_issue(self, repo: str, key: str) -> Issue | None:
        return None

    def open_or_update_issue(self, repo: str, key: str, title: str, body: str) -> str:
        self.calls.append(("open_or_update_issue", (repo, key, title, body)))
        return key

    def comment_issue(self, repo: str, key: str, body: str) -> None:
        self.calls.append(("comment_issue", (repo, key, body)))

    def revoke_consent(self, repo: str, key: str, diff_id: str) -> None:
        self.calls.append(("revoke_consent", (repo, key, diff_id)))

    def open_or_update_proposal(self, repo: str, branch: str, title: str, files: dict[str, str], body: str) -> str:
        self.calls.append(("open_or_update_proposal", (repo, branch, title, files, body)))
        return branch

    def apply_settings(
        self, repo: str, payload: dict[str, Any], *, expected_live: dict[str, Any] | None = None
    ) -> SettingsApplyResult:
        self.calls.append(("apply_settings", (repo, payload, expected_live)))
        return SettingsApplyResult()

    def create_repo(self, repo: str, *, private: bool) -> None:
        self.calls.append(("create_repo", (repo, private)))

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


_platform_contract: Platform = FakePlatform()


def _consumer(tmp_path: Path) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(
        "profile: python-library\nversion: v0\nvariables:\n  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    return tmp_path


def test_drift_report_rejects_invalid_declared_enum_before_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = _consumer(tmp_path)
    (consumer / ".github" / "aviato.yaml").write_text(
        "profile: node-service\nversion: v0\nvariables:\n  project-name: sample\n  language-variant: ruby\n",
        encoding="utf-8",
    )
    fake = FakePlatform()
    monkeypatch.setattr(cli, "GitHubPlatform", lambda workdir=None: fake)
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:owner/repo.git")

    rc = cli.main(["drift-report", str(consumer)])

    captured = capsys.readouterr()
    assert rc == 2
    assert "language-variant" in captured.err
    assert fake.calls == []


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
    assert isinstance(files, dict)
    assert files, "proposal had no files"
    assert all("aviato:managed" in body for body in files.values())
    # settings drift reported (never applied)
    assert "apply_settings" not in fake.call_names()


def test_drift_report_reports_content_drifted_ruleset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # §5.6 (H-1): a CONTENT-drifted ruleset (same name, weakened) — not just a missing one — is
    # detected end-to-end and surfaced with declaration-aware remediation guidance.
    import copy

    from aviato.cli import _profile_status_checks
    from aviato.rulesets import render_all_rulesets

    live = copy.deepcopy(render_all_rulesets(extra_status_checks=_profile_status_checks("python-library")))
    for ruleset in live:
        if ruleset["target"] == "tag":
            ruleset["enforcement"] = "disabled"  # same name, but disabled = drift
    consumer = _consumer(tmp_path)
    fake = FakePlatform(settings={"required_reviews": 1}, rulesets=live)
    monkeypatch.setattr(cli, "GitHubPlatform", lambda workdir=None: fake)
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:owner/repo.git")

    rc = cli.main(["drift-report", str(consumer), "--settings-only"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Common: release tag format" in out
    # C12-3: the remediation now points at the override-aware `--declaration` form, so an apply does
    # not re-add a check the consumer removed via overrides.
    assert "--declaration" in out and ".github/aviato.yaml" in out


def test_drift_report_file_only_skips_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # §5.6/§11.2 least-privilege: --file-only runs file drift under the platform token and
    # never touches settings, so the workflow can run it WITHOUT the admin settings-token.
    consumer = _consumer(tmp_path)
    fake = FakePlatform(settings={"required_reviews": 1})
    monkeypatch.setattr(cli, "GitHubPlatform", lambda workdir=None: fake)
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:owner/repo.git")
    diagnosis_calls: list[dict[str, object]] = []
    monkeypatch.setattr("aviato.cli.diagnose", _record_keyword_arguments(diagnose, diagnosis_calls))
    rc = cli.main(["drift-report", str(consumer), "--file-only"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "open_or_update_proposal" in fake.call_names()  # file drift ran
    assert "settings drift" not in out  # settings never attempted
    expected_inputs = cli._diagnosis_probe_inputs(Registry(MODULE_SOURCE_ROOT), "python-library")
    assert {key: diagnosis_calls[0][key] for key in expected_inputs} == expected_inputs


def test_drift_report_settings_only_skips_file_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # --settings-only runs only the settings read (under the admin token in its own step);
    # file-drift writes are not performed, so that token never sees a write operation.
    consumer = _consumer(tmp_path)
    fake = FakePlatform(settings={"required_reviews": 1})
    monkeypatch.setattr(cli, "GitHubPlatform", lambda workdir=None: fake)
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:owner/repo.git")
    rc = cli.main(["drift-report", str(consumer), "--settings-only"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "open_or_update_proposal" not in fake.call_names()  # file drift skipped
    assert "settings drift" in out


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
    # The real read_settings raises SettingsReadError on a read failure; the fake mirrors it.
    from aviato.github import SettingsReadError

    consumer = _consumer(tmp_path)

    class NoAdminPlatform(FakePlatform):
        def read_settings(self, repo: str) -> dict[str, Any]:
            raise SettingsReadError(f"repos/{repo}/branches/main/protection", 1, "HTTP 403: Forbidden")

    fake = NoAdminPlatform()
    monkeypatch.setattr(cli, "GitHubPlatform", lambda workdir=None: fake)
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:owner/repo.git")

    rc = cli.main(["drift-report", str(consumer)])
    captured = capsys.readouterr()
    assert rc == 0  # did not crash
    assert "open_or_update_proposal" in fake.call_names()  # file drift still ran
    assert "settings drift: skipped" in captured.err
    assert "apply_settings" not in fake.call_names()  # never mutates


def test_drift_report_require_settings_fails_on_unreadable_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # §5.6 gating: --require-settings makes an unreadable-settings skip exit non-zero so a CI
    # gate can tell "skipped" from "clean" (the default still exits 0 — see the test above).
    from aviato.github import SettingsReadError

    consumer = _consumer(tmp_path)

    class NoAdminPlatform(FakePlatform):
        def read_settings(self, repo: str) -> dict[str, Any]:
            raise SettingsReadError(f"repos/{repo}/branches/main/protection", 1, "HTTP 403: Forbidden")

    fake = NoAdminPlatform()
    monkeypatch.setattr(cli, "GitHubPlatform", lambda workdir=None: fake)
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:owner/repo.git")

    rc = cli.main(["drift-report", str(consumer), "--require-settings"])
    captured = capsys.readouterr()
    assert rc == 1  # skip is now a failure under --require-settings
    assert "settings drift: skipped" in captured.err
    assert "apply_settings" not in fake.call_names()  # still never mutates


def test_drift_report_fails_loud_when_issue_channel_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # §5.6: an ISSUE-CHANNEL failure (issues disabled / API error opening the tracking issue)
    # must FAIL LOUD — never be silently downgraded to a "settings skipped" exit 0. The
    # settings READ succeeds here; only the issue write fails.
    from aviato.github import GitHubAPIError

    consumer = _consumer(tmp_path)

    class IssueChannelDownPlatform(FakePlatform):
        def open_or_update_issue(self, repo: str, key: str, title: str, body: str) -> str:
            raise GitHubAPIError(f"repos/{repo}/issues", 1, "HTTP 410: Issues are disabled")

    # Non-empty live settings that differ from desired → a real diff that must be reported.
    fake = IssueChannelDownPlatform(settings={"required_reviews": 0})
    monkeypatch.setattr(cli, "GitHubPlatform", lambda workdir=None: fake)
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:owner/repo.git")

    rc = cli.main(["drift-report", str(consumer), "--settings-only"])
    captured = capsys.readouterr()
    assert rc == 1  # fails loud, NOT a silent skip
    assert "issue" in captured.err.lower()
    assert "skipped" not in captured.err  # must not masquerade as a settings-read skip
    assert "apply_settings" not in fake.call_names()  # never mutates


def test_drift_report_rejects_file_only_with_require_settings(tmp_path: Path) -> None:
    # §5.6: --require-settings is a silent no-op under --file-only; reject the contradiction
    # so a CI gate is not misled into thinking it enforces a settings read.
    from aviato.cli import main

    rc = main(["drift-report", str(tmp_path), "--file-only", "--require-settings"])
    assert rc == 2


def test_drifted_rulesets_honors_required_reviews_override() -> None:
    # CX#1: the ruleset render used for drift must honor the consumer's required_reviews override,
    # so the ruleset surface agrees with the classic-protection reconcile (no phantom drift / no
    # apply that resets approvals). Live rulesets carry approvals=2 (the overridden value).
    from aviato.cli import _drifted_rulesets, _profile_status_checks
    from aviato.rulesets import render_all_rulesets

    checks = _profile_status_checks("python-library")
    live = render_all_rulesets(required_approvals=2, extra_status_checks=checks)
    platform = FakePlatform(rulesets=live)
    # With the override threaded through, desired==live → NO drift.
    assert _drifted_rulesets("o/r", platform, required_approvals=2, extra_status_checks=checks) == ()
    # Without it (policy default 1), desired (1) != live (2) → the branch ruleset reports drift.
    assert _drifted_rulesets("o/r", platform, extra_status_checks=checks) != ()


def test_drifted_rulesets_uses_resolved_checks_not_base_profile() -> None:
    # R9-21 (cycle 11): drift compares against the OVERRIDE-RESOLVED required status checks supplied
    # by the caller, not the base profile. A consumer that removed a pipeline (→ empty extra checks)
    # must not see phantom drift against live rulesets that also carry no extra checks.
    from aviato.cli import _drifted_rulesets
    from aviato.rulesets import render_all_rulesets

    live = render_all_rulesets(extra_status_checks=[])
    platform = FakePlatform(rulesets=live)
    assert _drifted_rulesets("o/r", platform, extra_status_checks=[]) == ()
