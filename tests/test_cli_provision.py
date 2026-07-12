from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aviato import __version__, cli
from aviato.cli import main
from aviato.core.provision import ProvisionOutcome


class _FakePlatform:
    def __init__(self, skipped: list[str] | None = None) -> None:
        self.applied: list[tuple[str, dict[str, Any]]] = []
        # R2-4-3: apply_settings now returns the §17 toggles it surfaced-and-skipped.
        self.skipped = skipped or []

    def apply_settings(self, repo: str, payload: dict[str, Any]) -> list[str]:
        self.applied.append((repo, payload))
        return list(self.skipped)


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
    monkeypatch.setattr(
        cli,
        "_published_library_ref_exists",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pin probe must not run")),
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


def test_provision_refuses_unpublished_pin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "_published_library_ref_exists", lambda pin: False)
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
    assert "--allow-unresolved-pin" in err


def test_provision_partial_outcome_reports_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: object())
    monkeypatch.setattr(
        cli,
        "provision_repo",
        lambda *a, **k: ProvisionOutcome(
            created=True,
            minimal_applied=True,
            scaffolded=True,
            full_applied=False,
            partial=True,
            reason="protection rejected",
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
            "--allow-unresolved-pin",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )
    assert rc == 1  # partial provisioning is a non-zero exit pointing at complete-protection


def test_provision_exposed_state_reports_unprotected_and_recovery(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # §8.7: created but minimal protection failed → the repo EXISTS and is UNPROTECTED; the CLI
    # must say so (not the benign "partial" message) and point at complete-protection, exit 1.
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: object())
    monkeypatch.setattr(
        cli,
        "provision_repo",
        lambda *a, **k: ProvisionOutcome(created=True, minimal_applied=False, partial=True, reason="403"),
    )
    rc = main(
        [
            "provision",
            "o/r",
            "--profile",
            "python-library",
            "--pin",
            "0",
            "--allow-unresolved-pin",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "UNPROTECTED" in err and "complete-protection" in err


def test_provision_success_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "GitHubPlatform", lambda *a, **k: object())
    monkeypatch.setattr(
        cli,
        "provision_repo",
        lambda *a, **k: ProvisionOutcome(
            created=True, minimal_applied=True, scaffolded=True, full_applied=True, partial=False
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
            "--allow-unresolved-pin",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )
    assert rc == 0


def test_provision_success_reports_skipped_unavailable_toggle(
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
            partial=False,
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
            "--allow-unresolved-pin",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "SKIPPED" in err and "secret_scanning" in err and "§17" in err
