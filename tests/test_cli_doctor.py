from __future__ import annotations

from types import SimpleNamespace

import pytest

from aviato import cli, rulesets
from aviato.cli import main
from aviato.core.diagnosis import DiagnosisReport
from aviato.core.model import VariableSpec


@pytest.mark.parametrize(
    ("docs", "serve_pages", "expected_probe"),
    [(False, True, False), (True, False, False), (True, True, True)],
)
def test_doctor_probes_pages_only_for_docs_and_serve_pages(
    tmp_path, monkeypatch, capsys, docs: bool, serve_pages: bool, expected_probe: bool
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

    def fake_diagnose(*args, **kwargs):
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

    def probe(self, repo, **kwargs):
        seen.append(kwargs["probe_pages_build_type"])
        assert kwargs["desired_rulesets"]
        return None, None, {"drift_automation_enabled": True, "ruleset_protection_full": False}

    monkeypatch.setattr(cli.GitHubPlatform, "probe_health", probe)
    assert main(["doctor", str(tmp_path)]) == 0
    assert seen == [expected_probe]
    expected_inputs = cli._diagnosis_probe_inputs(cli.Registry(cli.MODULE_SOURCE_ROOT), "python-service")
    assert {key: diagnosis_calls[0][key] for key in expected_inputs} == expected_inputs
    assert "ruleset_protection_full: no" in capsys.readouterr().out


def test_onboard_secret_value_never_prints_in_doctor_facing_plan(tmp_path, monkeypatch, capsys) -> None:
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
    tmp_path,
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
        cli.GitHubPlatform,
        "probe_health",
        lambda *args, **kwargs: (None, None, {"drift_automation_enabled": remote_enabled}),
    )

    assert main(["doctor", str(tmp_path)]) == expected_rc
    output = capsys.readouterr().out
    assert f"drift automation present locally: {'yes' if local_present else 'no'}" in output
    assert f"drift automation enabled remotely: {remote_text}" in output
