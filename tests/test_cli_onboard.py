from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest
import yaml

from aviato.cli import main
from aviato.core.scaffold import ScaffoldItem as _ScaffoldItem
from aviato.core.scaffold import scaffold

ScaffoldItem = partial(_ScaffoldItem, input_hash="0" * 64)


def _adopt(tmp_path: Path, *extra: str) -> int:
    return main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--allow-dirty",
            "--allow-unresolved-pin",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
            *extra,
        ]
    )


@pytest.mark.parametrize("from_slug_arg", [True, False])
def test_autodetect_fills_owner_and_repo_from_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, from_slug_arg: bool
) -> None:
    # §5.2 auto-detection: both `owner` AND `repo` are READ from the authoritative repo slug
    # (the slug argument for proposal paths, or the git remote) — same source/authority. `repo`
    # is the second slug segment, exactly as `owner` is the first.
    from aviato import cli

    if from_slug_arg:
        detected = cli._autodetect_vars("octocat/hello-world")
    else:
        monkeypatch.setattr(cli, "remote_url", lambda r: "git@github.com:octocat/hello-world.git")
        monkeypatch.setattr(cli, "normalize_slug", lambda remote: "octocat/hello-world")
        detected = cli._autodetect_vars(str(tmp_path))
    assert detected == {"owner": "octocat", "repo": "hello-world"}


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


def test_onboard_plan_echoes_and_validates_pin(capsys: pytest.CaptureFixture[str]) -> None:
    # review #29: the dry-run plan must preview the canonical pin --write would record (legacy v
    # stripped), and a malformed --pin must be rejected (exit 2), not silently ignored.
    rc = main(["onboard", "owner/repo", "--profile", "python-library", "--pin", "v1.2.3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "version pin: 1.2.3" in out  # canonicalized (no leading v)
    rc = main(["onboard", "owner/repo", "--profile", "python-library", "--pin", "not-a-pin"])
    assert rc == 2  # malformed pin rejected on the plan path too


def test_malformed_var_on_plan_path_is_clean_error_not_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    # review #8: a malformed --var on the (unguarded) plan path used to escape as a raw traceback
    # + exit 1. The top-level main() safety net must turn ANY leaked AviatoError into a clean
    # stderr message + exit 2 — no command path may ever surface a stack trace.
    rc = main(["onboard", "owner/repo", "--profile", "python-library", "--var", "novalue"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "KEY=VALUE" in err or "novalue" in err


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
    (github / "aviato.yaml").write_text(
        "profile: python-library\nversion: v1\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
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


def test_doctor_rejects_bootstrap_declaration_in_non_library(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # §5.4/§5.10: a `bootstrap: true` declaration is only valid in the Library itself (detected by
    # structure). In any other repo, doctor must reject it with a clean error (exit 2), not a
    # traceback. This proves the diagnose() bootstrap guard is actually WIRED from the CLI — the
    # tmp_path repo has no aviato/library structure, so is_library(root) is False.
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(
        "profile: python-library\nversion: v1\nbootstrap: true\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    rc = main(["doctor", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "bootstrap" in err.lower() and "library" in err.lower()
