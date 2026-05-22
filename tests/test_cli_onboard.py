from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aviato.cli import main
from aviato.core.scaffold import ScaffoldItem, scaffold


def _adopt(tmp_path: Path, *extra: str) -> int:
    return main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--allow-dirty",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
            *extra,
        ]
    )


def test_onboard_lists_composed_pipelines_and_variables(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["onboard", "owner/repo", "--profile", "python-library"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "profile: python-library" in out
    assert "security-baseline" in out  # always-on baseline
    assert "pypi-publish" in out  # python-library deploy
    assert "distribution-name" in out  # required variable
    # The apply-rulesets guidance must carry --profile so the operator applies the
    # profile's language verify check (not just the weaker common ruleset).
    assert "--profile python-library" in out


def test_onboard_unknown_profile_fails(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["onboard", "owner/repo", "--profile", "does-not-exist"])
    assert rc != 0


def test_onboard_plan_hides_docs_artifacts_unless_opted_in(capsys: pytest.CaptureFixture[str]) -> None:
    # §6.1: the plan must list the EXACT artifacts that would be written. With docs off
    # (the default) the docs caller workflow and website artifacts must not appear.
    rc = main(["onboard", "owner/repo", "--profile", "python-library"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "aviato-docs.yml" not in out
    assert "website/" not in out

    # With --docs the docs-gated artifacts appear.
    rc = main(["onboard", "owner/repo", "--profile", "python-library", "--docs"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "aviato-docs.yml" in out


def test_onboard_plan_does_not_list_conflicting_variant_templates(capsys: pytest.CaptureFixture[str]) -> None:
    # §6.1/§4.2: node-service has two templates writing package.json gated on mutually-
    # exclusive language-variant. The plan must list the EXACT set --write materializes, so
    # the top-level package.json must appear AT MOST once, never both variants at once.
    rc = main(["onboard", "owner/repo", "--profile", "node-service"])
    out = capsys.readouterr().out
    assert rc == 0
    pkg_lines = [ln for ln in out.splitlines() if ln.strip().startswith("- package.json ")]
    assert len(pkg_lines) <= 1, pkg_lines


def test_reonboard_without_pin_preserves_existing(tmp_path: Path) -> None:
    # §5.12: onboarding is not a re-pin. A fresh adopt with a legacy ``v2.0.0`` is
    # canonicalized to bare on write (§6.1); re-onboarding without --pin must preserve it.
    assert _adopt(tmp_path, "--pin", "v2.0.0") == 0
    decl = tmp_path / ".github" / "aviato.yaml"
    assert yaml.safe_load(decl.read_text())["version"] == "2.0.0"

    assert _adopt(tmp_path) == 0  # no --pin
    assert yaml.safe_load(decl.read_text())["version"] == "2.0.0"


def test_reonboard_with_differing_pin_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # §5.12: an explicit --pin that moves the recorded pin is refused — the operator
    # is directed to the dedicated re-pin path rather than silently moving it.
    assert _adopt(tmp_path, "--pin", "2.0.0") == 0
    capsys.readouterr()
    rc = _adopt(tmp_path, "--pin", "1.0.0")
    err = capsys.readouterr().err
    assert rc != 0
    assert "repin" in err
    # The pin was NOT moved.
    decl = tmp_path / ".github" / "aviato.yaml"
    assert yaml.safe_load(decl.read_text())["version"] == "2.0.0"


def test_reonboard_with_matching_pin_ok(tmp_path: Path) -> None:
    assert _adopt(tmp_path, "--pin", "2.0.0") == 0
    assert _adopt(tmp_path, "--pin", "v2.0.0") == 0  # legacy form, same pin → allowed
    decl = tmp_path / ".github" / "aviato.yaml"
    assert yaml.safe_load(decl.read_text())["version"] == "2.0.0"


def test_doctor_reports_clean_and_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # A consumer repo declaring python-library with one matching managed file present.
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: v1\n", encoding="utf-8")
    # scaffold the editorconfig body exactly as the resolved set expects
    from aviato.core.composition import resolve_profile
    from aviato.core.registry import Registry
    from aviato.paths import MODULE_SOURCE_ROOT

    reg = Registry(MODULE_SOURCE_ROOT)
    rs = resolve_profile(reg, "python-library")
    editorconfig = next(t for t in rs.templates if t.output_path == ".editorconfig")
    body = reg.template_body(editorconfig)
    scaffold(tmp_path, [ScaffoldItem(".editorconfig", body, "#", False)], profile="python-library", version="v1")

    rc = main(["doctor", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert ".editorconfig" in out
    assert "clean" in out
    assert "missing" in out  # other managed files are absent
