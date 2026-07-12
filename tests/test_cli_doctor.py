from __future__ import annotations

from types import SimpleNamespace

from aviato import cli, rulesets
from aviato.cli import main
from aviato.core.model import VariableSpec


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
