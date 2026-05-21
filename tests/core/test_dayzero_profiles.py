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


def test_pypi_pipeline_declares_oidc_privilege(registry: Registry) -> None:
    rs = resolve_profile(registry, "python-library")
    pypi = next(m for m in rs.pipeline_modules if m.name == "pypi-publish")
    assert "id-token: write" in pypi.privileges
    assert pypi.secrets == ()  # OIDC, no stored secret (§13.1)


def test_app_store_pipeline_declares_secrets_and_macos(registry: Registry) -> None:
    rs = resolve_profile(registry, "swift-app")
    asc = next(m for m in rs.pipeline_modules if m.name == "app-store-connect")
    assert "APP_STORE_CONNECT_KEY_ID" in asc.secrets
    assert asc.runner == "macos"


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


def test_services_deploy_ghcr(registry: Registry) -> None:
    assert "ghcr-publish" in resolve_profile(registry, "python-service").pipelines
    assert "ghcr-publish" in resolve_profile(registry, "node-service").pipelines


def test_swift_app_requires_macos_and_deploys_app_store(registry: Registry) -> None:
    rs = resolve_profile(registry, "swift-app")
    assert registry.profile("swift-app").requires_macos is True
    assert "app-store-connect" in rs.pipelines


@pytest.mark.parametrize("name", DAYZERO)
def test_profile_scaffolds_caller_workflows(registry: Registry, name: str) -> None:
    # §15: a consumer actually receives the verify/release/deploy/security CI caller
    # and the scheduled drift/report workflow — not just composed pipeline names.
    outputs = {t.output_path for t in resolve_profile(registry, name).templates}
    assert ".github/workflows/aviato-ci.yml" in outputs
    assert ".github/workflows/aviato-drift.yml" in outputs


def test_node_ci_workflow_renders_typecheck_from_variant() -> None:
    from aviato.core.onboarding import materialize_items

    reg = Registry(MODULE_SOURCE_ROOT)
    js = next(
        i
        for i in materialize_items(reg, "node-service", {"language-variant": "javascript"})
        if i.output == ".github/workflows/aviato-ci.yml"
    )
    ts = next(
        i
        for i in materialize_items(reg, "node-service", {"language-variant": "typescript"})
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


def test_docs_opt_in_scaffolds_runnable_docusaurus_site() -> None:
    # §13.3/#4: docs:true must scaffold a *runnable* site (config + sidebars + a docs
    # package with docusaurus deps + at least one source page), not just a config.
    from aviato.core.onboarding import materialize_items

    reg = Registry(MODULE_SOURCE_ROOT)
    variables = {"distribution-name": "acme", "import-name": "acme"}
    outputs_off = {i.output for i in materialize_items(reg, "python-library", variables, docs=False)}
    items_on = materialize_items(reg, "python-library", variables, docs=True)
    outputs_on = {i.output for i in items_on}

    expected = {
        "website/docusaurus.config.js",
        "website/sidebars.js",
        "website/package.json",
        "website/docs/intro.md",
    }
    assert expected <= outputs_on
    assert not (expected & outputs_off)  # none scaffolded without the opt-in

    pkg = next(i for i in items_on if i.output == "website/package.json")
    assert "@docusaurus/preset-classic" in pkg.body
    assert "@easyops-cn/docusaurus-search-local" in pkg.body
    assert '"build": "docusaurus build"' in pkg.body


def test_python_profile_scaffolds_pyproject_manifest() -> None:
    # §3.3/#6: onboarding must seed the version-source manifest with the dev tools the
    # default CI invokes (pytest-cov, build) so verify/build jobs are runnable.
    from aviato.core.onboarding import materialize_items

    reg = Registry(MODULE_SOURCE_ROOT)
    item = next(
        i
        for i in materialize_items(reg, "python-library", {"distribution-name": "acme", "import-name": "acme"})
        if i.output == "pyproject.toml"
    )
    assert item.seed_once is True
    assert 'version = "0.1.0"' in item.body
    assert "pytest-cov" in item.body
    assert "build>=" in item.body
    assert 'name = "acme"' in item.body  # lenient render filled the package name


def test_node_typescript_manifest_has_tsc_and_engines() -> None:
    from aviato.core.onboarding import materialize_items

    reg = Registry(MODULE_SOURCE_ROOT)
    items = [
        i
        for i in materialize_items(reg, "node-service", {"project-name": "acme", "language-variant": "typescript"})
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
    from aviato.core.onboarding import materialize_items

    reg = Registry(MODULE_SOURCE_ROOT)
    items = [
        i
        for i in materialize_items(reg, "node-service", {"project-name": "acme", "language-variant": "javascript"})
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
    from aviato.core.onboarding import materialize_items

    reg = Registry(MODULE_SOURCE_ROOT)
    variables = {
        "product-scheme": "Acme",
        "bundle-identifier": "com.acme.app",
        "team-id": "ABCDE12345",
        "export-method": "app-store",
    }
    ci = next(
        i for i in materialize_items(reg, "swift-app", variables) if i.output == ".github/workflows/aviato-ci.yml"
    )
    assert 'scheme: "Acme"' in ci.body
    assert 'bundle-identifier: "com.acme.app"' in ci.body
    assert 'team-id: "ABCDE12345"' in ci.body
    assert 'export-method: "app-store"' in ci.body
    assert "com.example.app" not in ci.body
    assert "TEAMID1234" not in ci.body


@pytest.mark.parametrize("name", DAYZERO)
def test_docs_opt_in_composes_docs_pipeline(registry: Registry, name: str) -> None:
    assert "docs-pages" not in resolve_profile(registry, name).pipelines
    assert "docs-pages" in resolve_profile(registry, name, docs=True).pipelines


def test_node_language_variant_is_enum(registry: Registry) -> None:
    rs = resolve_profile(registry, "node-service")
    variant = next(v for v in rs.variables if v.name == "language-variant")
    assert variant.type == "enum"
    assert variant.domain == ("typescript", "javascript")
