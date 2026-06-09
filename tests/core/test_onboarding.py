from __future__ import annotations

from pathlib import Path

import pytest

from aviato.core.declaration import Declaration
from aviato.core.errors import CompositionError, DeclarationError
from aviato.core.model import TemplateModule
from aviato.core.onboarding import (
    check_output_collisions,
    materialize_items,
    plan_onboarding,
)
from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT


def test_output_collision_among_applicable_templates_is_error() -> None:
    # §4.2: two applicable templates writing the same path is a tie, not a silent pick.
    colliding = [
        TemplateModule(output_path="config.toml", source="a"),
        TemplateModule(output_path="config.toml", source="b"),
    ]
    with pytest.raises(CompositionError):
        check_output_collisions(colliding)


def test_variant_exclusive_templates_sharing_a_path_are_allowed() -> None:
    # package.json.ts / package.json.js render to the same path but are mutually
    # exclusive via `when`; only one is ever applicable, so this is NOT a collision.
    ts = TemplateModule(output_path="package.json", source="ts", when=(("language-variant", "typescript"),))
    check_output_collisions([ts])  # the applicable set for one variant — no raise


def test_docs_true_scaffolds_gated_docs_workflow() -> None:
    reg = Registry(MODULE_SOURCE_ROOT)
    variables = {"distribution-name": "acme", "import-name": "acme"}
    without = {i.output for i in materialize_items(reg, "python-library", variables)}
    withdocs = {i.output: i for i in materialize_items(reg, "python-library", variables, docs=True)}
    assert ".github/workflows/aviato-docs.yml" not in without
    docs = withdocs[".github/workflows/aviato-docs.yml"]
    # §4/§5.14: docs deploy is gated by the release gate AND the release-ref security baseline.
    assert "reusable-release-gate.yml" in docs.body
    assert "reusable-security-baseline.yml" in docs.body
    assert "needs: [resolve, release-gate, security]" in docs.body
    # In-run model (#1): triggered by workflow_run (token-pushed tags don't re-trigger),
    # deploying only when the completed run carries a fresh release tag.
    assert "workflow_run:" in docs.body
    assert "release-tag: ${{ needs.resolve.outputs.tag }}" in docs.body


def test_pin_is_stamped_into_generated_workflows() -> None:
    reg = Registry(MODULE_SOURCE_ROOT)
    items = {i.output: i for i in materialize_items(reg, "python-library", {}, pin="v1.2.3")}
    ci = items[".github/workflows/aviato-ci.yml"].body
    assert "@v1.2.3" in ci  # reusable workflow refs pinned (§2.6/§6.1)
    assert "@main" not in ci
    drift = items[".github/workflows/aviato-drift.yml"].body
    assert "aviato-ref: v1.2.3" in drift


def test_bootstrap_uses_local_workflow_refs_and_local_install() -> None:
    reg = Registry(MODULE_SOURCE_ROOT)
    items = {
        i.output: i
        for i in materialize_items(
            reg,
            "python-library",
            {"distribution-name": "aviato", "import-name": "aviato"},
            pin="0",
            bootstrap=True,
        )
    }
    ci = items[".github/workflows/aviato-ci.yml"].body
    assert "uses: ./.github/workflows/reusable-python-ci.yml" in ci
    assert "uses: amattas/aviato/.github/workflows/" not in ci
    assert "local-install: true" in ci
    drift = items[".github/workflows/aviato-drift.yml"].body
    assert "uses: ./.github/workflows/reusable-consumer-automation.yml" in drift
    assert "local-install: true" in drift


def test_javascript_variant_omits_tsconfig_and_disables_typecheck() -> None:
    from aviato.core.onboarding import render_variables

    reg = Registry(MODULE_SOURCE_ROOT)
    ts_items = {i.output for i in materialize_items(reg, "node-service", {"language-variant": "typescript"})}
    js_items = {i.output for i in materialize_items(reg, "node-service", {"language-variant": "javascript"})}
    assert "tsconfig.json" in ts_items
    assert "tsconfig.json" not in js_items  # §12.2: JS omits TypeScript config
    # run-typecheck is derived from the profile's data-driven derived_variables rule
    # (no language literal in core); apply it the same way resolved_artifacts does.
    rules = reg.profile_doc("node-service")["derived_variables"]
    assert render_variables({"language-variant": "javascript"}, derived_rules=rules)["run-typecheck"] == "false"
    assert render_variables({"language-variant": "typescript"}, derived_rules=rules)["run-typecheck"] == "true"


def test_materialize_builds_scaffold_items_from_resolved_set() -> None:
    reg = Registry(MODULE_SOURCE_ROOT)
    items = materialize_items(reg, "python-library", variables={})
    by_output = {item.output: item for item in items}
    assert ".editorconfig" in by_output
    assert by_output[".editorconfig"].seed_once is False
    assert by_output["LICENSE"].seed_once is True  # non-annotatable, seed-once


def test_materialize_renders_into_scaffold_then_writes(tmp_path: Path) -> None:
    from aviato.core.scaffold import scaffold

    reg = Registry(MODULE_SOURCE_ROOT)
    items = materialize_items(reg, "python-library", variables={})
    result = scaffold(tmp_path, items, profile="python-library", version="v1")
    assert ".editorconfig" in result.written
    assert (tmp_path / "ruff.toml").read_text().startswith("# aviato:managed profile=python-library")
    # LICENSE is seed-once (no marker)
    assert "aviato:managed" not in (tmp_path / "LICENSE").read_text()


def test_plan_onboarding_adopt_clean(tmp_path: Path) -> None:
    reg = Registry(MODULE_SOURCE_ROOT)
    plan = plan_onboarding(reg, profile="python-library", existing_declaration=None, variables={})
    assert plan.profile == "python-library"
    assert plan.outputs  # lists the files it would materialize


def test_plan_onboarding_refuses_profile_change_without_migrate() -> None:
    reg = Registry(MODULE_SOURCE_ROOT)
    existing = Declaration(profile="node-service", version="v1")
    with pytest.raises(DeclarationError):
        plan_onboarding(reg, profile="python-library", existing_declaration=existing, variables={})


def test_plan_onboarding_allows_same_profile_reonboard() -> None:
    reg = Registry(MODULE_SOURCE_ROOT)
    existing = Declaration(profile="python-library", version="v1")
    plan = plan_onboarding(reg, profile="python-library", existing_declaration=existing, variables={})
    assert plan.profile == "python-library"


def test_plan_onboarding_allows_profile_change_with_migrate() -> None:
    reg = Registry(MODULE_SOURCE_ROOT)
    existing = Declaration(profile="node-service", version="v1")
    plan = plan_onboarding(
        reg, profile="python-library", existing_declaration=existing, variables={}, allow_migrate=True
    )
    assert plan.profile == "python-library"
