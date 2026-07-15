from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aviato import __version__, cli
from aviato.cli import main
from aviato.core.errors import AviatoError
from aviato.core.ports import Issue, Platform, RepositoryIdentity
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

    def repository_identity(self, repo: str) -> RepositoryIdentity:
        return RepositoryIdentity(7, "R_7", repo, "main")

    def read_protection_state(
        self, repo: str, *, environments: tuple[str, ...] = (), aviato_pin: str = ""
    ) -> dict[str, Any]:
        return {"repository_identity": self.repository_identity(repo)}

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


def test_complete_protection_defaults_to_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _consumer(tmp_path)
    platform = _FakePlatform()
    monkeypatch.setattr(cli, "remote_url", lambda r: "git@github.com:o/r.git")
    monkeypatch.setattr(cli, "normalize_slug", lambda remote: "o/r")
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: platform)
    monkeypatch.setattr(
        cli,
        "build_protection_plan",
        lambda **_kwargs: SimpleNamespace(plan_id="a" * 64, ready=True, blockers=()),
    )

    rc = main(["complete-protection", str(root)])
    assert rc == 0
    assert platform.applied == []


def test_complete_protection_apply_requires_exact_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # R2-4-3/R2-5-F1: when apply_settings surfaces-and-skips an unavailable §17 toggle, the CLI must
    # NOT claim a clean apply — it must name the skipped toggle and point at §17.
    root = _consumer(tmp_path)
    platform = _FakePlatform()
    monkeypatch.setattr(cli, "remote_url", lambda r: "git@github.com:o/r.git")
    monkeypatch.setattr(cli, "normalize_slug", lambda remote: "o/r")
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: platform)
    monkeypatch.setattr(
        cli,
        "build_protection_plan",
        lambda **_kwargs: SimpleNamespace(plan_id="a" * 64, ready=True, blockers=()),
    )

    rc = main(["complete-protection", str(root), "--apply", "--confirm", "wrong"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "exact --confirm" in err
    assert platform.applied == []


def test_complete_protection_authority_expiry_before_operation_is_clean_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _consumer(tmp_path)
    platform = _FakePlatform()
    plan = SimpleNamespace(plan_id="a" * 64, ready=True, blockers=())
    writes: list[str] = []
    monkeypatch.setattr(cli, "remote_url", lambda _root: "git@github.com:o/r.git")
    monkeypatch.setattr(cli, "normalize_slug", lambda _remote: "o/r")
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: platform)
    monkeypatch.setattr(cli, "build_protection_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(cli, "require_protection_confirmation", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(cli, "resolve_receipt_signing_identity", lambda **_kwargs: {"principal": "reviewer"})
    monkeypatch.setattr(
        cli,
        "_refresh_privileged_mutation_authority",
        lambda _root: (_ for _ in ()).throw(AviatoError("live privileged review expired")),
    )

    def execute(*_args: object, **kwargs: object) -> object:
        authorize = kwargs["authorize"]
        assert callable(authorize)
        try:
            authorize()
        except AviatoError:
            return SimpleNamespace(receipt=SimpleNamespace(ready=False, status="failed"))
        writes.append("write")
        raise AssertionError("expired authority must not write")

    monkeypatch.setattr(cli, "execute_protection_plan", execute)
    rc = main(
        [
            "complete-protection",
            str(root),
            "--apply",
            "--confirm",
            "a" * 64,
            "--receipt-principal",
            "reviewer",
            "--receipt-key-id",
            "1",
            "--receipt-signing-key",
            str(tmp_path / "key"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1 and writes == []
    assert "did not converge: failed" in captured.err and "Traceback" not in captured.err


def test_complete_protection_missing_declaration_errors(tmp_path: Path) -> None:
    assert main(["complete-protection", str(tmp_path)]) == 2


def test_provision_rejects_bad_slug() -> None:
    assert main(["provision", "no-slash", "--profile", "python-library"]) == 2


def test_provision_authority_expiry_before_create_is_clean_fail_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    platform = _FakePlatform()
    created: list[str] = []
    monkeypatch.setattr(platform, "create_repo", lambda repo, **_kwargs: created.append(repo))
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: platform)
    monkeypatch.setattr(
        cli,
        "_refresh_privileged_mutation_authority",
        lambda _root: (_ for _ in ()).throw(AviatoError("live privileged review expired")),
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
    captured = capsys.readouterr()
    assert rc == 1 and created == []
    assert "expired" in captured.err and "Traceback" not in captured.err


def test_release_checkpoint_parser_exposes_real_lifecycle_commands() -> None:
    parser = cli.build_parser()
    for phase in ("collect", "review-sign", "verify", "persist"):
        args = parser.parse_args(["release-checkpoint", phase])
        assert args.func is not None


@pytest.mark.parametrize("phase", ("collect", "review-sign", "verify", "persist"))
def test_release_checkpoint_invalid_phase_input_is_clean_exit_two_without_traceback(
    phase: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["release-checkpoint", phase]) == 2
    captured = capsys.readouterr()
    assert "requires --" in captured.err
    assert "Traceback" not in captured.err


def test_provision_parser_requires_explicit_apply_confirmation_and_degraded_consent() -> None:
    args = cli.build_parser().parse_args(["provision", "o/r", "--pin", "1"])
    assert args.apply is False and args.confirm is None and args.allow_degraded_tag_pattern is False


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
        assert callable(kwargs["full_protection"])
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


def test_packaged_pending_review_attestation_blocks_privileged_mutation() -> None:
    from aviato.paths import MODULE_SOURCE_ROOT
    from aviato.plugins.release_mutations import verify_packaged_privileged_review_readiness

    errors = verify_packaged_privileged_review_readiness(MODULE_SOURCE_ROOT)
    assert any("protected review is pending" in error for error in errors)


@pytest.mark.parametrize(
    "argv",
    (
        ["apply-rulesets", "o/r", "--pin", "1", "--apply"],
        ["provision", "o/r", "--pin", "1"],
    ),
)
def test_privileged_entrypoints_refuse_before_remote_work(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_require_privileged_mutation_readiness", lambda *_args: False, raising=False)
    monkeypatch.setattr(
        cli,
        "GitHubPlatform",
        lambda: (_ for _ in ()).throw(AssertionError("blocked privileged command must not construct a platform")),
    )
    assert cli.main(argv) == 1
