from __future__ import annotations

import pytest

from aviato.core.composition import resolve_profile
from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT

DAYZERO = ("python-library", "python-service", "python-component", "node-service", "swift-app")


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry(MODULE_SOURCE_ROOT)


@pytest.mark.parametrize("name", DAYZERO)
def test_dayzero_profile_resolves(registry: Registry, name: str) -> None:
    rs = resolve_profile(registry, name)
    assert rs.pipelines
    assert rs.templates


@pytest.mark.parametrize("name", DAYZERO)
def test_security_baseline_present_in_every_profile(registry: Registry, name: str) -> None:
    rs = resolve_profile(registry, name)
    assert "security-baseline" in rs.pipelines  # §2.13 always-on


@pytest.mark.parametrize("name", DAYZERO)
def test_release_gate_present_in_every_profile(registry: Registry, name: str) -> None:
    rs = resolve_profile(registry, name)
    assert "release-gate" in rs.pipelines


@pytest.mark.parametrize("name", DAYZERO)
def test_pipelines_resolve_to_typed_modules_with_privileges(registry: Registry, name: str) -> None:
    rs = resolve_profile(registry, name)
    by_name = {m.name: m for m in rs.pipeline_modules}
    # every composed pipeline has a typed module declaring privileges (§3.2/§11.3)
    assert set(rs.pipelines) == set(by_name)
    assert by_name["security-baseline"].privileges  # declared, non-empty
    assert "security-events: write" in by_name["security-baseline"].privileges


def test_pypi_pipeline_declares_local_publisher_oidc_privilege(registry: Registry) -> None:
    rs = resolve_profile(registry, "python-library")
    pypi = next(m for m in rs.pipeline_modules if m.name == "pypi-publish")
    assert "id-token: write" in pypi.privileges
    assert pypi.secrets == ()  # OIDC, no stored secret (§13.1)


def test_app_store_pipeline_declares_secrets_and_macos(registry: Registry) -> None:
    rs = resolve_profile(registry, "swift-app")
    asc = next(m for m in rs.pipeline_modules if m.name == "app-store-connect")
    assert "APP_STORE_CONNECT_KEY_ID" in asc.secrets
    assert asc.runner == "macos"
    assert asc.environment == "app-store-connect"
    assert asc.environment_input == "environment-name"


@pytest.mark.parametrize("name", DAYZERO)
def test_security_baseline_modeled_in_settings(registry: Registry, name: str) -> None:
    # §2.13: the reconcilable repo security toggles are modeled desired state.
    rs = resolve_profile(registry, name)
    security = rs.settings.get("security", {})
    assert security.get("secret_scanning") is True
    assert security.get("secret_push_protection") is True
    assert security.get("dependency_scanning") is True
    # Code scanning (SAST) is delivered by the always-composed pipeline, not a toggle.
    assert "security-baseline" in rs.pipelines
    assert "code_scanning" not in security  # not a perpetually-undriftable setting


def test_python_library_deploys_pypi(registry: Registry) -> None:
    assert "pypi-publish" in resolve_profile(registry, "python-library").pipelines


def test_python_component_has_no_deploy(registry: Registry) -> None:
    pipelines = resolve_profile(registry, "python-component").pipelines
    assert "pypi-publish" not in pipelines
    assert "ghcr-publish" not in pipelines


def test_python_scaffold_requires_supported_runtime_and_ruff_target(registry: Registry) -> None:
    from aviato.core.onboarding import resolved_artifacts

    artifacts = resolved_artifacts(
        registry,
        "python-component",
        {"distribution-name": "acme", "import-name": "acme"},
        pin="1.2.3",
    )
    bodies = {artifact.output: artifact.body for artifact in artifacts}
    assert 'requires-python = ">=3.12"' in bodies["pyproject.toml"]
    assert 'target-version = "py312"' in bodies["ruff.toml"]


def test_python_component_custom_typecheck_command_is_rendered(registry: Registry) -> None:
    from aviato.core.onboarding import resolved_artifacts

    artifacts = resolved_artifacts(
        registry,
        "python-component",
        {
            "distribution-name": "acme",
            "import-name": "acme",
            "typecheck-command": "python -m mypy --strict src/acme",
        },
        pin="1.2.3",
    )
    ci = next(artifact.body for artifact in artifacts if artifact.output == ".github/workflows/aviato-ci.yml")
    assert 'typecheck-command: "python -m mypy --strict src/acme"' in ci


def test_services_deploy_ghcr(registry: Registry) -> None:
    assert "ghcr-publish" in resolve_profile(registry, "python-service").pipelines
    assert "ghcr-publish" in resolve_profile(registry, "node-service").pipelines


def test_python_service_is_a_container_service_not_a_library(registry: Registry) -> None:
    # The Python container-service model: the build artifact is the Docker image, so the profile
    # declares no wheel/import packaging vars (§13.2) and versions via a packaging-free VERSION file
    # (not pyproject.toml). Mirrors node-service — including NO image-name var (R4-2): the GHCR image
    # defaults to the repo slug.
    rs = resolve_profile(registry, "python-service")
    var_names = {v.name for v in rs.variables}
    # Only the every-profile vars — `default-branch` (R4-3), `owner` (finding 28), and the
    # optional docs-site metadata vars `repo`/`project-name` (seed the zensical.toml);
    # there is no required container-service-specific variable (no wheel/import packaging,
    # no image-name).
    assert var_names == {
        "default-branch",
        "owner",
        "repo",
        "project-name",
        "serve-pages",
    }, var_names
    assert "distribution-name" not in var_names and "import-name" not in var_names
    assert "image-name" not in var_names
    assert rs.version_source is not None
    assert rs.version_source.locations == ("VERSION",)
    # The scaffold seeds VERSION + requirements-dev.txt and does NOT seed a pyproject.toml.
    from aviato.core.onboarding import resolved_artifacts

    arts = resolved_artifacts(registry, "python-service", {}, pin="1", docs=False)
    outputs = {a.output for a in arts}
    seed_once = {a.output for a in arts if a.seed_once}
    assert "VERSION" in seed_once and "requirements-dev.txt" in seed_once
    assert "pyproject.toml" not in outputs
    # The CI caller installs from requirements, never `pip install -e .`, and builds no wheel.
    ci = next(a.body for a in arts if a.output == ".github/workflows/aviato-ci.yml")
    assert "pip install -e ." not in ci
    assert "requirements-dev.txt" in ci and "run-build: false" in ci


def test_swift_app_requires_macos_and_deploys_app_store(registry: Registry) -> None:
    rs = resolve_profile(registry, "swift-app")
    assert "app-store-connect" in rs.pipelines
    # review #17: macOS-requirement is derived from the resolved pipelines' data-driven runner,
    # not a profile-level flag — swift-app composes at least one macos pipeline.
    modules = [registry.pipeline_module(p) for p in rs.pipelines]
    runners = {module.runner for module in modules if module is not None}
    assert "macos" in runners


@pytest.mark.parametrize("name", DAYZERO)
def test_profile_scaffolds_caller_workflows(registry: Registry, name: str) -> None:
    # §15: a consumer actually receives the verify/release/deploy/security CI caller
    # and the scheduled drift/report workflow — not just composed pipeline names.
    outputs = {t.output_path for t in resolve_profile(registry, name).templates}
    assert ".github/workflows/aviato-ci.yml" in outputs
    assert ".github/workflows/aviato-drift.yml" in outputs


def test_node_ci_workflow_renders_typecheck_from_variant() -> None:
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    js = next(
        i
        for i in resolved_artifacts(
            reg, "node-service", {"project-name": "acme", "language-variant": "javascript"}, pin="0"
        )
        if i.output == ".github/workflows/aviato-ci.yml"
    )
    ts = next(
        i
        for i in resolved_artifacts(
            reg, "node-service", {"project-name": "acme", "language-variant": "typescript"}, pin="0"
        )
        if i.output == ".github/workflows/aviato-ci.yml"
    )
    assert "run-typecheck: false" in js.body
    assert "run-typecheck: true" in ts.body


@pytest.mark.parametrize(
    ("name", "verify_check"),
    [
        ("python-library", "ci / Python CI"),
        ("node-service", "ci / Node CI"),
        ("swift-app", "ci / Swift CI"),
    ],
)
def test_required_status_checks_include_language_verify(registry: Registry, name: str, verify_check: str) -> None:
    # §10/#5: the merge gate must require the language verify job, not only the
    # common-lint + security-baseline checks — derived from composed pipelines.
    checks = resolve_profile(registry, name).settings["default_branch"]["required_status_checks"]
    assert verify_check in checks
    assert "common-lint / Common lint" in checks
    assert "security / Security baseline heartbeat" in checks


def test_common_scaffold_ships_shared_governance_files() -> None:
    # §12.1 (finding 48): contributing, code owners, and issue/PR templates come from
    # the common scaffold — seed-once, so the consumer owns them after seeding.
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    expected = {
        "CONTRIBUTING.md",
        ".github/CODEOWNERS",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/pull_request_template.md",
    }
    for profile, variables in (
        ("python-library", {"distribution-name": "a", "import-name": "a"}),
        ("node-service", {"project-name": "a", "language-variant": "typescript"}),
    ):
        items = resolved_artifacts(reg, profile, variables, pin="0")
        outputs = {i.output for i in items}
        assert expected <= outputs, (profile, expected - outputs)
        assert all(i.seed_once for i in items if i.output in expected)

    owned = resolved_artifacts(
        reg, "python-library", {"distribution-name": "a", "import-name": "a", "owner": "octocat"}, pin="0"
    )
    codeowners = next(i for i in owned if i.output == ".github/CODEOWNERS")
    assert "* @octocat" in codeowners.body


def test_unset_optional_variables_never_render_as_none() -> None:
    # finding 28: resolve_variables emits None for unset optionals; the render layer
    # must omit them (placeholder preserved), never bake the literal "None".
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    variables = {"distribution-name": "acme", "import-name": "acme", "owner": None}
    items = resolved_artifacts(reg, "python-library", variables, pin="0")
    license_body = next(i.body for i in items if i.output == "LICENSE")
    assert "None" not in license_body
    assert "{{ owner }}" in license_body


def test_owner_variable_seeds_license() -> None:
    # finding 28: a detected owner (CLI autodetect tier) lands in the seed-once LICENSE.
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    variables = {"distribution-name": "acme", "import-name": "acme", "owner": "octocat"}
    items = resolved_artifacts(reg, "python-library", variables, pin="0")
    license_body = next(i.body for i in items if i.output == "LICENSE")
    assert "octocat" in license_body
    assert "{{ owner }}" not in license_body


def test_docs_opt_in_scaffolds_zensical_site() -> None:
    # §13.3/#4: docs:true must scaffold a Zensical site — the site config, a source
    # page, and a pinned docs toolchain requirements.txt — and none of it without the
    # opt-in. Zensical consumes plain markdown, so there is no config.js / sidebars /
    # package.json / eslint / algolia surface anymore.
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    variables = {"distribution-name": "acme", "import-name": "acme"}
    outputs_off = {i.output for i in resolved_artifacts(reg, "python-library", variables, docs=False, pin="0")}
    items_on = resolved_artifacts(reg, "python-library", variables, docs=True, pin="0")
    outputs_on = {i.output for i in items_on}

    expected = {
        "website/zensical.toml",
        "website/docs/index.md",
        "website/requirements.txt",
    }
    assert expected <= outputs_on
    assert not (expected & outputs_off)  # none scaffolded without the opt-in
    # The retired Docusaurus scaffold surface is gone entirely.
    assert not any(
        "docusaurus" in o or "algolia" in o or o.endswith(("sidebars.js", "package.json", "eslint.config.mjs"))
        for o in outputs_on
    )

    config = next(i for i in items_on if i.output == "website/zensical.toml")
    assert "[project]" in config.body
    assert 'site_name = "{{ project-name }}"' in config.body  # seed-once keeps the placeholder
    assert 'provider = "mike"' in config.body  # multi-version docs via mike

    reqs = next(i for i in items_on if i.output == "website/requirements.txt")
    assert "zensical==0.0.50" in reqs.body
    assert "mike @ git+https://github.com/squidfunk/mike.git@" in reqs.body


def test_python_profile_scaffolds_pyproject_manifest() -> None:
    # §3.3/#6: onboarding must seed the version-source manifest with the dev tools the
    # default CI invokes (pytest-cov, build) so verify/build jobs are runnable.
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    item = next(
        i
        for i in resolved_artifacts(
            reg,
            "python-library",
            {"distribution-name": "acme", "import-name": "acme"},
            pin="0",
        )
        if i.output == "pyproject.toml"
    )
    assert item.seed_once is True
    assert 'version = "0.1.0"' in item.body
    assert "pytest-cov" in item.body
    # finding 12: the seeded dev extras are EXACT-pinned (==), like requirements-dev —
    # CI installs them via `-e .[dev]`, so floors would float invisibly (§11.3).
    assert "build==" in item.body
    assert ">=" not in item.body.split("[project.optional-dependencies]", 1)[1].split("[", 1)[0]
    # §12.1 (finding 48): measure-only test+coverage config ships in the manifest.
    assert "[tool.pytest.ini_options]" in item.body
    assert "[tool.coverage.run]" in item.body
    assert 'source = ["acme"]' in item.body
    assert 'name = "acme"' in item.body  # lenient render filled the package name


def test_node_typescript_manifest_has_tsc_and_engines() -> None:
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    items = [
        i
        for i in resolved_artifacts(
            reg, "node-service", {"project-name": "acme", "language-variant": "typescript"}, pin="0"
        )
        if i.output == "package.json"
    ]
    assert len(items) == 1  # only the TS-gated manifest applies
    body = items[0].body
    assert items[0].seed_once is True
    assert '"version": "0.1.0"' in body
    assert '"name": "acme"' in body
    assert '"engines"' in body  # §12.2 requires engines
    assert "tsc --noEmit" in body
    assert '"typescript"' in body


def test_node_javascript_manifest_omits_typescript() -> None:
    # §12.2/#8: the JavaScript variant must not get tsc type-check/build or a
    # TypeScript dev dependency, but still declares engines.
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    items = [
        i
        for i in resolved_artifacts(
            reg, "node-service", {"project-name": "acme", "language-variant": "javascript"}, pin="0"
        )
        if i.output == "package.json"
    ]
    assert len(items) == 1  # only the JS-gated manifest applies
    body = items[0].body
    assert '"engines"' in body
    assert "tsc" not in body
    assert "typescript" not in body
    assert "typecheck" not in body


def test_swift_caller_consumes_declared_variables() -> None:
    # §12.3/#7: the declared onboarding variables must be stamped into the generated
    # caller workflow — no hardcoded "App"/"com.example.app"/"TEAMID1234" left behind.
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    variables = {
        "product-scheme": "Acme",
        "workspace": "AcmeApp.xcworkspace",
        "bundle-identifier": "com.acme.app",
        "team-id": "ABCDE12345",
        "export-method": "app-store",
        "environment-name": "production",
        "export-options-plist": "Config/ExportOptions.plist",
        "version-command": "./scripts/set-version.sh",
    }
    ci = next(
        i
        for i in resolved_artifacts(reg, "swift-app", variables, pin="0")
        if i.output == ".github/workflows/aviato-ci.yml"
    )
    assert 'scheme: "Acme"' in ci.body
    assert 'workspace: "AcmeApp.xcworkspace"' in ci.body
    assert 'environment-name: "production"' in ci.body
    assert 'export-options-plist: "Config/ExportOptions.plist"' in ci.body
    assert 'version-command: "./scripts/set-version.sh"' in ci.body
    assert 'bundle-identifier: "com.acme.app"' in ci.body
    assert 'team-id: "ABCDE12345"' in ci.body
    assert 'export-method: "app-store"' in ci.body
    assert "com.example.app" not in ci.body
    assert "TEAMID1234" not in ci.body


def test_swift_caller_requires_workspace_or_project() -> None:
    from aviato.core.errors import DeclarationError
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    variables = {
        "product-scheme": "Acme",
        "bundle-identifier": "com.acme.app",
        "team-id": "ABCDE12345",
        "export-method": "app-store",
    }
    with pytest.raises(DeclarationError, match="workspace|project"):
        resolved_artifacts(reg, "swift-app", variables, pin="0")


@pytest.mark.parametrize("name", DAYZERO)
def test_docs_opt_in_composes_docs_pipeline(registry: Registry, name: str) -> None:
    assert "docs-pages" not in resolve_profile(registry, name).pipelines
    assert "docs-pages" in resolve_profile(registry, name, docs=True).pipelines


@pytest.mark.parametrize("name", DAYZERO)
def test_docs_profiles_default_pages_serving_off(registry: Registry, name: str) -> None:
    resolved = resolve_profile(registry, name)
    serve = next(variable for variable in resolved.variables if variable.name == "serve-pages")
    assert serve.type == "boolean"
    assert serve.required is False
    assert serve.default is False


def test_serve_pages_rejects_non_boolean_declaration(registry: Registry) -> None:
    from aviato.core.errors import DeclarationError
    from aviato.core.onboarding import resolved_artifacts

    with pytest.raises(DeclarationError, match="serve-pages.*not a boolean"):
        resolved_artifacts(
            registry,
            "python-service",
            {"serve-pages": "certainly"},
            pin="0",
            docs=True,
        )


def test_node_language_variant_is_enum(registry: Registry) -> None:
    rs = resolve_profile(registry, "node-service")
    variant = next(v for v in rs.variables if v.name == "language-variant")
    assert variant.type == "enum"
    assert variant.domain == ("typescript", "javascript")


@pytest.mark.parametrize("variant", ["typescript", "javascript"])
def test_node_eslint_config_is_runnable(variant: str) -> None:
    # §16/#8: the managed ESLint flat config must actually load. It uses ESM imports, so
    # it is materialized as `eslint.config.mjs` (ESM regardless of the package type), and
    # every plugin it imports must be a declared dependency or `eslint .` fails on a fresh
    # repo with "Cannot find module".
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    items = resolved_artifacts(reg, "node-service", {"project-name": "acme", "language-variant": variant}, pin="0")
    eslint = next(i for i in items if i.output == "eslint.config.mjs")
    assert 'import security from "eslint-plugin-security"' in eslint.body
    assert 'import js from "@eslint/js"' in eslint.body
    pkg = next(i for i in items if i.output == "package.json")
    assert "eslint-plugin-security" in pkg.body  # imported plugin is declared
    assert "@eslint/js" in pkg.body  # imported config is declared


@pytest.mark.parametrize("variant", ["typescript", "javascript"])
def test_node_projects_scaffold_npm_hardening_config(variant: str) -> None:
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    items = resolved_artifacts(reg, "node-service", {"project-name": "acme", "language-variant": variant}, pin="0")
    npmrc = next(i for i in items if i.output == ".npmrc")
    assert "min-release-age=7" in npmrc.body
    assert "ignore-scripts=true" in npmrc.body
    assert "engine-strict=true" in npmrc.body
    pkg = next(i for i in items if i.output == "package.json")
    assert '"node": ">=24.0"' in pkg.body
    assert '"npm": ">=11.10.0"' in pkg.body  # finding 13: min-release-age needs npm >=11.10


def test_node_javascript_has_no_fake_build_gate() -> None:
    # §16/#8: the JS variant must not pass a vacuous `npm run build`. There is no compile
    # step for plain JS (the production artifact is the Docker image), so the source-CI
    # build gate is disabled, and the placeholder build script does not silently succeed.
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    items = resolved_artifacts(reg, "node-service", {"project-name": "acme", "language-variant": "javascript"}, pin="0")
    ci = next(i for i in items if i.output == ".github/workflows/aviato-ci.yml")
    assert "run-build: false" in ci.body
    pkg = next(i for i in items if i.output == "package.json")
    assert "exit 1" in pkg.body  # not a silent echo-and-pass


def test_node_typescript_runs_real_build_gate() -> None:
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    items = resolved_artifacts(reg, "node-service", {"project-name": "acme", "language-variant": "typescript"}, pin="0")
    ci = next(i for i in items if i.output == ".github/workflows/aviato-ci.yml")
    assert "run-build: true" in ci.body
    pkg = next(i for i in items if i.output == "package.json")
    assert '"build": "tsc --build"' in pkg.body


def test_swift_caller_installs_apple_swift_format() -> None:
    # §12.3: the reusable Swift CI requires Apple's `swift-format`; the scaffold must
    # install that exact tool, not the differently-named `swiftformat` (which would make
    # the generated CI fail at `command -v swift-format`).
    from aviato.core.onboarding import resolved_artifacts

    reg = Registry(MODULE_SOURCE_ROOT)
    variables = {
        "product-scheme": "Acme",
        "workspace": "AcmeApp.xcworkspace",
        "bundle-identifier": "com.acme.app",
        "team-id": "ABCDE12345",
        "export-method": "app-store",
    }
    ci = next(
        i
        for i in resolved_artifacts(reg, "swift-app", variables, pin="0")
        if i.output == ".github/workflows/aviato-ci.yml"
    )
    assert "swift-format" in ci.body
    # No bare `swiftformat` (the wrong tool): removing the correct token leaves none behind.
    assert "swiftformat" not in ci.body.replace("swift-format", "")


def test_default_branch_templates_into_caller_triggers(registry: Registry) -> None:
    # R4-3: GitHub Actions trigger `branches:` can't use `${{ }}`, so the default branch is a
    # render-time literal. Default is `main`; a consumer on another default branch overrides the
    # `default-branch` variable and the generated CI caller's push/PR triggers + release-gate input
    # follow — otherwise CI/release gating would silently never fire on their branch.
    from aviato.core.onboarding import resolved_artifacts

    def ci_body(variables: dict[str, str]) -> str:
        arts = resolved_artifacts(registry, "python-library", variables, pin="1", docs=False)
        return next(a.body for a in arts if a.output == ".github/workflows/aviato-ci.yml")

    base = {"distribution-name": "d", "import-name": "pkg"}
    default = ci_body(base)
    assert 'branches: ["main"]' in default
    overridden = ci_body({**base, "default-branch": "trunk"})
    assert 'branches: ["trunk"]' in overridden
    assert 'branches: ["main"]' not in overridden
    assert "default-branch: trunk" in overridden


def test_python_service_omits_image_name_input_like_node_service(registry: Registry) -> None:
    # R4-2: python-service declares no image-name var and its GHCR caller passes no image-name input
    # — the image defaults to the repo slug in reusable-docker-ghcr.yml, exactly like node-service.
    # Resolving with empty variables must succeed (no unset-placeholder strict-render failure) and
    # the rendered docker job must carry no image-name line.
    from aviato.core.onboarding import resolved_artifacts

    py = resolved_artifacts(registry, "python-service", {}, pin="1", docs=False)
    node = resolved_artifacts(
        registry, "node-service", {"project-name": "a", "language-variant": "typescript"}, pin="1", docs=False
    )
    py_ci = next(a.body for a in py if a.output == ".github/workflows/aviato-ci.yml")
    node_ci = next(a.body for a in node if a.output == ".github/workflows/aviato-ci.yml")

    def sets_image_name(body: str) -> bool:
        # An actual workflow INPUT line (ignore an explanatory `# … image-name: …` comment).
        return any(line.strip().startswith("image-name:") for line in body.splitlines())

    assert not sets_image_name(py_ci)
    assert not sets_image_name(node_ci)
