from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aviato import __version__, cli
from aviato.cli import main
from aviato.core.ports import Issue, Platform
from aviato.core.provision import ProvisionOutcome

pytestmark = pytest.mark.usefixtures("task3_pinned_context")


class _FakePlatform:
    def __init__(self, skipped: list[str] | None = None) -> None:
        self.applied: list[tuple[str, dict[str, Any]]] = []
        # R2-4-3: apply_settings now returns the §17 toggles it surfaced-and-skipped.
        self.skipped = skipped or []

    def apply_settings(
        self, repo: str, payload: dict[str, Any], *, expected_live: dict[str, Any] | None = None
    ) -> list[str]:
        self.applied.append((repo, payload))
        return list(self.skipped)

    def read_settings(self, repo: str) -> dict[str, Any]:
        return {}

    def read_rulesets(self, repo: str) -> list[dict[str, Any]]:
        return []

    def get_issue(self, repo: str, key: str) -> Issue | None:
        return None

    def open_or_update_issue(self, repo: str, key: str, title: str, body: str) -> str:
        return key

    def comment_issue(self, repo: str, key: str, body: str) -> None:
        pass

    def revoke_consent(self, repo: str, key: str, diff_id: str) -> None:
        pass

    def open_or_update_proposal(self, repo: str, branch: str, title: str, files: dict[str, str], body: str) -> str:
        return branch

    def create_repo(self, repo: str, *, private: bool) -> None:
        pass


_platform_contract: Platform = _FakePlatform()


def test_transition_workdir_cleanup_retains_pending_clone_and_prints_exact_recovery_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workdir = tmp_path / "workdir"
    repository = workdir / "repo"
    (repository / ".git").mkdir(parents=True)
    removed: list[Path] = []
    monkeypatch.setattr(cli, "inspect_transition", lambda _root: SimpleNamespace(pending=True))
    monkeypatch.setattr(cli.shutil, "rmtree", lambda path, **_kwargs: removed.append(Path(path)))

    cli._cleanup_transition_workdir(workdir, repository)

    assert removed == []
    assert f"aviato recover-transition {repository}" in capsys.readouterr().err


def _consumer(tmp_path: Path) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(
        f"profile: python-library\nversion: {__version__}\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    return tmp_path


def test_complete_protection_applies_full_desired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _consumer(tmp_path)
    platform = _FakePlatform()
    monkeypatch.setattr(cli, "remote_url", lambda r: "git@github.com:o/r.git")
    monkeypatch.setattr(cli, "normalize_slug", lambda remote: "o/r")
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: platform)

    rc = main(["complete-protection", str(root)])
    assert rc == 0
    assert platform.applied and platform.applied[0][0] == "o/r"
    # Full desired state carries the always-on protections (e.g. PR requirement).
    assert platform.applied[0][1].get("requires_pull_request") is True


def test_complete_protection_reports_skipped_unavailable_toggle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # R2-4-3/R2-5-F1: when apply_settings surfaces-and-skips an unavailable §17 toggle, the CLI must
    # NOT claim a clean apply — it must name the skipped toggle and point at §17.
    root = _consumer(tmp_path)
    platform = _FakePlatform(skipped=["secret_scanning"])
    monkeypatch.setattr(cli, "remote_url", lambda r: "git@github.com:o/r.git")
    monkeypatch.setattr(cli, "normalize_slug", lambda remote: "o/r")
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: platform)

    rc = main(["complete-protection", str(root)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "SKIPPED" in err and "secret_scanning" in err and "§17" in err


def test_complete_protection_missing_declaration_errors(tmp_path: Path) -> None:
    assert main(["complete-protection", str(tmp_path)]) == 2


def test_provision_rejects_bad_slug() -> None:
    assert main(["provision", "no-slash", "--profile", "python-library"]) == 2


@pytest.mark.parametrize(
    "slug",
    ["a/b/c", "a/b?x", "a/b#x", " a/b", "a/b ", "-a/b", "a/-b", "a\\b", "a/b\n", "a/", "/b"],
)
def test_provision_rejects_unsafe_slug_before_platform_calls(slug: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "provision_repo",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provision must not run")),
    )
    argv = ["provision", "--profile", "python-library", "--pin", "0"]
    if slug.startswith("-"):
        argv.append("--")
    assert main([*argv, slug]) == 2


def test_provision_requires_explicit_pin(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "provision",
            "o/r",
            "--profile",
            "python-library",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "--pin" in err


def test_provision_rejects_unknown_flag_variable_before_remote_mutation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "provision_repo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provision must not run for unknown variables")),
    )

    rc = main(
        [
            "provision",
            "o/r",
            "--profile",
            "python-library",
            "--pin",
            "0",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
            "--var",
            "distribution-naem=typo",
        ]
    )

    assert rc == 2
    assert "distribution-naem" in capsys.readouterr().err


def test_provision_refuses_unpublished_pin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from aviato.core.errors import AviatoError

    monkeypatch.setattr(
        cli,
        "_open_published_snapshot",
        lambda _pin: (_ for _ in ()).throw(AviatoError("Library pin '0' does not resolve")),
    )
    rc = main(
        [
            "provision",
            "o/r",
            "--profile",
            "python-library",
            "--pin",
            "0",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "does not resolve" in err
    assert "does not resolve" in err


def test_provision_reports_partial_full_protection_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: object())
    monkeypatch.setattr(
        cli,
        "provision_repo",
        lambda *a, **k: ProvisionOutcome(
            created=True,
            minimal_applied=True,
            scaffolded=True,
            partial=True,
            reason="full protection failed",
        ),
    )
    rc = main(
        [
            "provision",
            "o/r",
            "--profile",
            "python-library",
            "--pin",
            "0",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )
    assert rc == 1
    assert "PARTIAL" in capsys.readouterr().err


def test_provision_reports_exposed_repository_when_minimal_protection_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # §8.7: created but minimal protection failed → the repo EXISTS and is UNPROTECTED; the CLI
    # must say so (not the benign "partial" message) and point at complete-protection, exit 1.
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: object())
    monkeypatch.setattr(
        cli,
        "provision_repo",
        lambda *a, **k: ProvisionOutcome(created=True, partial=True, reason="minimal failed"),
    )
    rc = main(
        [
            "provision",
            "o/r",
            "--profile",
            "python-library",
            "--pin",
            "0",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "UNPROTECTED" in err


def test_provision_clone_scaffold_uses_same_sidecar_inventory_and_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: object())
    clone_paths: list[Path] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["gh", "repo", "clone"]:
            clone_path = Path(command[4])
            clone_paths.append(clone_path)
            clone_path.mkdir(parents=True)
            subprocess.run(["git", "-C", str(clone_path), "init", "-q"], check=True)
            (clone_path / "README.md").write_text("operator seed\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    def fake_provision(*_args: object, **kwargs: object) -> ProvisionOutcome:
        callback = kwargs["scaffold_push"]
        assert callable(callback)
        callback()
        clone_path = clone_paths[0]
        assert (clone_path / ".github/aviato.yaml").is_file()
        assert (clone_path / ".github/aviato.seed.json").is_file()
        assert (clone_path / ".github/aviato.managed.yml").is_file()
        assert (clone_path / "README.md").read_text(encoding="utf-8") == "operator seed\n"
        return ProvisionOutcome(created=True, minimal_applied=True, scaffolded=True, full_applied=True)

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "provision_repo", fake_provision)
    rc = main(
        [
            "provision",
            "o/r",
            "--profile",
            "python-library",
            "--pin",
            "0",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )
    assert rc == 0
    assert capsys.readouterr().err == ""


def test_provision_reports_skipped_security_toggle(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # R2-1-PROV/R2-5-F1: a successful provision that surfaced-and-skipped a §17 toggle must say so
    # rather than imply the security setting landed with full protection.
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: object())
    monkeypatch.setattr(
        cli,
        "provision_repo",
        lambda *a, **k: ProvisionOutcome(
            created=True,
            minimal_applied=True,
            scaffolded=True,
            full_applied=True,
            skipped_security=["secret_scanning"],
        ),
    )
    rc = main(
        [
            "provision",
            "o/r",
            "--profile",
            "python-library",
            "--pin",
            "0",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "SKIPPED" in err and "secret_scanning" in err
