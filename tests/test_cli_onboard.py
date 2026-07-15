from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest
import yaml

from aviato.cli import main
from aviato.core.scaffold import ScaffoldItem as _ScaffoldItem
from aviato.core.scaffold import scaffold

ScaffoldItem = partial(_ScaffoldItem, input_hash="0" * 64)

pytestmark = pytest.mark.usefixtures("task3_pinned_context")


def _adopt(tmp_path: Path, *extra: str) -> int:
    pin = [] if (tmp_path / ".github/aviato.yaml").is_file() else ["--pin", "0"]
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
            *pin,
            *extra,
        ]
    )


def _write_legacy_declaration(
    tmp_path: Path,
    *,
    profile: str = "python-library",
    version: str = "2.0.0",
    variables: dict[str, str] | None = None,
) -> Path:
    declaration = tmp_path / ".github" / "aviato.yaml"
    declaration.parent.mkdir(parents=True, exist_ok=True)
    declaration.write_text(
        yaml.safe_dump(
            {
                "profile": profile,
                "profile-identity": f"aviato-profile/{profile}/v1",
                "version": version,
                "variables": variables or {"distribution-name": "acme", "import-name": "acme"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return declaration


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
    rc = main(["onboard", "owner/repo", "--profile", "python-library", "--pin", "0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "profile: python-library" in out
    assert "security-baseline" in out  # always-on baseline
    assert "pypi-publish" in out  # python-library deploy
    assert "distribution-name" in out  # required variable
    # A fresh preview has no declaration yet, so it must sequence declaration creation
    # before the override-aware ruleset command instead of recommending --profile.
    assert "after onboarding writes or updates the declaration" in out
    assert ("aviato apply-rulesets owner/repo --apply --declaration /path/to/checkout/.github/aviato.yaml") in out
    assert "apply-rulesets owner/repo --apply --profile" not in out


def test_onboard_unknown_profile_fails(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["onboard", "owner/repo", "--profile", "does-not-exist", "--pin", "0"])
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
    rc = main(["onboard", "owner/repo", "--profile", "python-library", "--pin", "0", "--var", "novalue"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "KEY=VALUE" in err or "novalue" in err


@pytest.mark.parametrize("mode", ["preview", "write"])
def test_unknown_flag_variable_is_rejected_before_preview_or_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    target = "owner/repo" if mode == "preview" else str(tmp_path)
    args = [
        "onboard",
        target,
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
    if mode == "write":
        args.extend(("--write", "--allow-dirty"))

    assert main(args) == 2
    captured = capsys.readouterr()
    assert "distribution-naem" in captured.err
    assert "Onboarding plan" not in captured.out
    assert not (tmp_path / ".github/aviato.yaml").exists()


@pytest.mark.parametrize(
    "bad_vars",
    [
        ("--var", "malformed"),
        ("--var", "project-name=one", "--var", "project-name=two"),
    ],
)
def test_preview_profile_migration_guard_precedes_malformed_or_duplicate_variables(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bad_vars: tuple[str, ...],
) -> None:
    _write_legacy_declaration(tmp_path)

    rc = main(["onboard", str(tmp_path), "--profile", "node-service", *bad_vars])

    captured = capsys.readouterr()
    assert rc == 2
    assert "--migrate-profile" in captured.err
    assert "KEY=VALUE" not in captured.err
    assert "given more than once" not in captured.err


def test_onboard_plan_hides_docs_artifacts_unless_opted_in(capsys: pytest.CaptureFixture[str]) -> None:
    # §6.1: the plan must list the EXACT artifacts that would be written. With docs off
    # (the default) the docs caller workflow and website artifacts must not appear.
    rc = main(["onboard", "owner/repo", "--profile", "python-library", "--pin", "0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "aviato-docs.yml" not in out
    assert "website/" not in out

    # With --docs the docs-gated artifacts appear.
    rc = main(["onboard", "owner/repo", "--profile", "python-library", "--pin", "0", "--docs"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "aviato-docs.yml" in out


def test_onboard_plan_does_not_list_conflicting_variant_templates(capsys: pytest.CaptureFixture[str]) -> None:
    # §6.1/§4.2: node-service has two templates writing package.json gated on mutually-
    # exclusive language-variant. The plan must list the EXACT set --write materializes, so
    # the top-level package.json must appear AT MOST once, never both variants at once.
    rc = main(["onboard", "owner/repo", "--profile", "node-service", "--pin", "0"])
    out = capsys.readouterr().out
    assert rc == 0
    pkg_lines = [ln for ln in out.splitlines() if ln.strip().startswith("- package.json ")]
    assert len(pkg_lines) <= 1, pkg_lines


@pytest.mark.parametrize(
    ("profile", "expected_environment"),
    [
        ("python-library", "pypi"),
        ("node-service", "ghcr"),
        ("swift-app", "app-store-connect"),
        ("python-component", None),
    ],
)
def test_onboard_plan_lists_protected_deployment_environment_requirements(
    profile: str, expected_environment: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["onboard", "owner/repo", "--profile", profile, "--pin", "0"]) == 0
    output = capsys.readouterr().out

    if expected_environment is None:
        assert "protected deployment environments: none" in output
    else:
        assert "protected deployment environments:" in output
        assert f"- {expected_environment}: must exist with at least one required reviewer before deploy" in output


def test_swift_onboard_plan_uses_resolved_environment_name_override(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "onboard",
                "owner/repo",
                "--profile",
                "swift-app",
                "--pin",
                "0",
                "--var",
                "environment-name=production",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out

    assert "- production: must exist with at least one required reviewer before deploy" in output
    assert "- app-store-connect:" not in output


@pytest.mark.parametrize(
    ("saved_environment", "cli_environment", "expected_environment"),
    [
        ("production", None, "production"),
        ("production", "staging", "staging"),
        (None, None, "app-store-connect"),
    ],
)
def test_swift_legacy_reonboard_plan_requires_repin_without_mutating_declaration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    saved_environment: str | None,
    cli_environment: str | None,
    expected_environment: str,
) -> None:
    variables = {
        "product-scheme": "Acme",
        "workspace": "Acme.xcworkspace",
        "bundle-identifier": "com.acme.app",
        "team-id": "ABCDE12345",
        "export-method": "app-store",
    }
    if saved_environment is not None:
        variables["environment-name"] = saved_environment
    declaration = tmp_path / ".github" / "aviato.yaml"
    declaration.parent.mkdir(parents=True)
    declaration.write_text(
        yaml.safe_dump(
            {
                "profile": "swift-app",
                "profile-identity": "aviato-profile/swift-app/v1",
                "version": "0",
                "variables": variables,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    original = declaration.read_text(encoding="utf-8")
    args = ["onboard", str(tmp_path), "--profile", "swift-app"]
    if cli_environment is not None:
        args += ["--var", f"environment-name={cli_environment}"]

    assert main(args) == 2
    captured = capsys.readouterr()

    assert "repin" in captured.err
    assert f"- {expected_environment}:" not in captured.out
    assert declaration.read_text(encoding="utf-8") == original


def test_legacy_reonboard_without_pin_requires_repin_and_preserves_existing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    decl = _write_legacy_declaration(tmp_path)
    original = decl.read_text(encoding="utf-8")

    assert _adopt(tmp_path) == 2
    assert "repin" in capsys.readouterr().err
    assert decl.read_text(encoding="utf-8") == original


def test_reonboard_with_differing_pin_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # §5.12: an explicit --pin that moves the recorded pin is refused — the operator
    # is directed to the dedicated re-pin path rather than silently moving it.
    decl = _write_legacy_declaration(tmp_path)
    original = decl.read_text(encoding="utf-8")
    rc = _adopt(tmp_path, "--pin", "1.0.0")
    err = capsys.readouterr().err
    assert rc != 0
    assert "repin" in err
    # The pin was NOT moved.
    assert decl.read_text(encoding="utf-8") == original


def test_legacy_reonboard_with_matching_pin_requires_repin_and_preserves_existing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    decl = _write_legacy_declaration(tmp_path)
    original = decl.read_text(encoding="utf-8")

    assert _adopt(tmp_path, "--pin", "v2.0.0") == 2
    assert "repin" in capsys.readouterr().err
    assert decl.read_text(encoding="utf-8") == original


def test_schema_v2_fresh_write_creates_declaration_and_managed_inventory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _adopt(tmp_path) == 0
    assert capsys.readouterr().err == ""
    assert (tmp_path / ".github/aviato.yaml").is_file()
    assert (tmp_path / ".github/aviato.managed.yml").is_file()


def test_doctor_reports_clean_and_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # A consumer repo declaring python-library with one matching managed file present.
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(
        "profile: python-library\nversion: v1\nvariables:\n  distribution-name: acme\n  import-name: acme\n",
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
    assert rc == 1  # remote automation state is unknown without a GitHub remote (§5.14)
    assert ".editorconfig" in out
    assert "clean" in out
    assert "missing" in out  # other managed files are absent
    assert "drift automation enabled remotely: unknown" in out


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
