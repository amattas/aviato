from __future__ import annotations

from pathlib import Path

import pytest

from aviato.cli import main
from aviato.core.scaffold import ScaffoldItem, scaffold


def test_onboard_lists_composed_pipelines_and_variables(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["onboard", "owner/repo", "--profile", "python-library"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "profile: python-library" in out
    assert "security-baseline" in out  # always-on baseline
    assert "pypi-publish" in out  # python-library deploy
    assert "distribution-name" in out  # required variable


def test_onboard_unknown_profile_fails(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["onboard", "owner/repo", "--profile", "does-not-exist"])
    assert rc != 0


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
