from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import yaml

from aviato import cli, rulesets
from aviato.cli import main
from aviato.core.diagnosis import DiagnosisReport
from aviato.core.model import VariableSpec
from aviato.core.registry import Registry
from aviato.github_platform import GitHubPlatform
from aviato.paths import MODULE_SOURCE_ROOT

pytestmark = pytest.mark.usefixtures("task3_pinned_context")


@pytest.mark.parametrize(
    ("docs", "serve_pages", "expected_probe"),
    [(False, True, False), (True, False, False), (True, True, True)],
)
def test_doctor_probes_pages_only_for_docs_and_serve_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    docs: bool,
    serve_pages: bool,
    expected_probe: bool,
) -> None:
    declaration = tmp_path / ".github" / "aviato.yaml"
    declaration.parent.mkdir(parents=True)
    declaration.write_text(
        "\n".join(
            [
                "profile: python-service",
                "version: '0'",
                f"docs: {str(docs).lower()}",
                "variables:",
                f"  serve-pages: {str(serve_pages).lower()}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_expected_artifacts", lambda *args, **kwargs: ())
    diagnosis_calls: list[dict[str, object]] = []

    def fake_diagnose(*args: object, **kwargs: object) -> SimpleNamespace:
        diagnosis_calls.append(kwargs)
        return SimpleNamespace(
            statuses={},
            seed_divergence=(),
            secret_in_declaration=False,
            drift_automation_present=True,
            drift_automation_enabled=True,
            drift_automation_healthy=True,
            prerequisites={},
            issue_channel_available=None,
            scan_heartbeat_present=None,
            prerequisites_remote={},
        )

    monkeypatch.setattr(cli, "diagnose", fake_diagnose)
    monkeypatch.setattr(cli, "remote_url", lambda root: "https://github.com/o/r.git")
    seen: list[bool] = []

    def probe(self: GitHubPlatform, repo: str, **kwargs: object) -> tuple[None, None, dict[str, bool]]:
        seen.append(cast(bool, kwargs["probe_pages_build_type"]))
        assert kwargs["desired_rulesets"]
        return None, None, {"drift_automation_enabled": True, "ruleset_protection_full": False}

    monkeypatch.setattr(GitHubPlatform, "probe_health", probe)
    assert main(["doctor", str(tmp_path)]) == 0
    assert seen == [expected_probe]
    expected_inputs = cli._diagnosis_probe_inputs(Registry(MODULE_SOURCE_ROOT), "python-service")
    assert {key: diagnosis_calls[0][key] for key in expected_inputs} == expected_inputs
    assert "ruleset_protection_full: no" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("declared_environment", "expected_environment"),
    [(None, "app-store-connect"), ("production", "production")],
)
def test_doctor_probes_swift_resolved_deployment_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    declared_environment: str | None,
    expected_environment: str,
) -> None:
    variable_lines = [
        "  product-scheme: Acme",
        "  workspace: Acme.xcworkspace",
        "  bundle-identifier: com.acme.app",
        "  team-id: ABCDE12345",
        "  export-method: app-store",
    ]
    if declared_environment is not None:
        variable_lines.append(f"  environment-name: {declared_environment}")
    declaration = tmp_path / ".github" / "aviato.yaml"
    declaration.parent.mkdir(parents=True)
    declaration.write_text(
        "profile: swift-app\nversion: '0'\nvariables:\n" + "\n".join(variable_lines) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_expected_artifacts", lambda *args, **kwargs: ())
    monkeypatch.setattr(
        cli,
        "diagnose",
        lambda *args, **kwargs: DiagnosisReport(drift_automation_present=True),
    )
    monkeypatch.setattr(cli, "remote_url", lambda root: "https://github.com/o/r.git")
    seen: list[tuple[str, ...]] = []

    def probe(self: GitHubPlatform, repo: str, **kwargs: object) -> tuple[None, None, dict[str, bool]]:
        seen.append(cast(tuple[str, ...], kwargs["environments"]))
        return None, None, {"drift_automation_enabled": True}

    monkeypatch.setattr(GitHubPlatform, "probe_health", probe)

    assert main(["doctor", str(tmp_path)]) == 0
    assert seen == [(expected_environment,)]


@pytest.mark.parametrize(
    ("profile", "variables", "expected_environment"),
    [
        ("python-library", {"distribution-name": "acme", "import-name": "acme"}, "pypi"),
        ("python-component", {"distribution-name": "acme", "import-name": "acme"}, None),
    ],
)
def test_doctor_preserves_static_or_absent_deployment_environments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    variables: dict[str, str],
    expected_environment: str | None,
) -> None:
    declaration = tmp_path / ".github" / "aviato.yaml"
    declaration.parent.mkdir(parents=True)
    declaration.write_text(
        yaml.safe_dump({"profile": profile, "version": "0", "variables": variables}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_expected_artifacts", lambda *args, **kwargs: ())
    monkeypatch.setattr(
        cli,
        "diagnose",
        lambda *args, **kwargs: DiagnosisReport(drift_automation_present=True),
    )
    monkeypatch.setattr(cli, "remote_url", lambda root: "https://github.com/o/r.git")
    seen: list[tuple[str, ...]] = []

    def probe(self: GitHubPlatform, repo: str, **kwargs: object) -> tuple[None, None, dict[str, bool]]:
        seen.append(cast(tuple[str, ...], kwargs["environments"]))
        return None, None, {"drift_automation_enabled": True}

    monkeypatch.setattr(GitHubPlatform, "probe_health", probe)

    assert main(["doctor", str(tmp_path)]) == 0
    expected = () if expected_environment is None else (expected_environment,)
    assert seen == [expected]


def test_onboard_secret_value_never_prints_in_doctor_facing_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    supplied_secret = "SUPER-SECRET-VALUE-DO-NOT-PRINT"
    resolved = SimpleNamespace(
        profile="test-profile",
        pipelines=(),
        variables=(VariableSpec(name="api-token", type="string", required=False, secret=True),),
    )
    monkeypatch.setattr(cli, "resolve_profile", lambda *args, **kwargs: resolved)
    monkeypatch.setattr(cli, "applicable_templates", lambda *args, **kwargs: ())
    monkeypatch.setattr(cli, "_profile_status_checks", lambda *args, **kwargs: ())
    monkeypatch.setattr(rulesets, "render_all_rulesets", lambda *args, **kwargs: ())

    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "test-profile",
            "--pin",
            "0",
            "--var",
            f"api-token={supplied_secret}",
        ]
    )
    output = capsys.readouterr().out
    assert rc == 0
    assert "api-token (string, optional, secret)" in output
    assert supplied_secret not in output


@pytest.mark.parametrize(
    ("local_present", "remote_enabled", "expected_rc", "remote_text"),
    [
        (True, True, 0, "yes"),
        (True, False, 1, "no"),
        (False, True, 1, "yes"),
        (True, None, 1, "unknown"),
    ],
)
def test_doctor_reports_local_and_remote_drift_automation_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    local_present: bool,
    remote_enabled: bool | None,
    expected_rc: int,
    remote_text: str,
) -> None:
    declaration = tmp_path / ".github" / "aviato.yaml"
    declaration.parent.mkdir(parents=True)
    declaration.write_text(
        "profile: python-library\nversion: '0'\nvariables:\n  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    report = DiagnosisReport(drift_automation_present=local_present)
    monkeypatch.setattr(cli, "_expected_artifacts", lambda *args, **kwargs: ())
    monkeypatch.setattr(cli, "diagnose", lambda *args, **kwargs: report)
    monkeypatch.setattr(cli, "remote_url", lambda root: "https://github.com/o/r.git")
    monkeypatch.setattr(
        GitHubPlatform,
        "probe_health",
        lambda *args, **kwargs: (None, None, {"drift_automation_enabled": remote_enabled}),
    )

    assert main(["doctor", str(tmp_path)]) == expected_rc
    output = capsys.readouterr().out
    assert f"drift automation present locally: {'yes' if local_present else 'no'}" in output
    assert f"drift automation enabled remotely: {remote_text}" in output
