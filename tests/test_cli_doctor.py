from __future__ import annotations

from types import SimpleNamespace

import pytest

from aviato import cli, rulesets
from aviato.cli import main
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
    monkeypatch.setattr(
        cli,
        "diagnose",
        lambda *args, **kwargs: SimpleNamespace(
            statuses={},
            seed_divergence=(),
            secret_in_declaration=False,
            drift_automation_present=True,
            prerequisites={},
            issue_channel_available=None,
            scan_heartbeat_present=None,
            prerequisites_remote={},
        ),
    )
    monkeypatch.setattr(cli, "remote_url", lambda root: "https://github.com/o/r.git")
    seen: list[bool] = []

    def probe(self, repo, **kwargs):
        seen.append(kwargs["probe_pages_build_type"])
        assert kwargs["desired_rulesets"]
        return None, None, {"ruleset_protection_full": False}

    monkeypatch.setattr(cli.GitHubPlatform, "probe_health", probe)
    assert main(["doctor", str(tmp_path)]) == 0
    assert seen == [expected_probe]
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
