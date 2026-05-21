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


def test_node_language_variant_is_enum(registry: Registry) -> None:
    rs = resolve_profile(registry, "node-service")
    variant = next(v for v in rs.variables if v.name == "language-variant")
    assert variant.type == "enum"
    assert variant.domain == ("typescript", "javascript")
