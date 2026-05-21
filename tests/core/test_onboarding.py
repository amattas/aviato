from __future__ import annotations

from pathlib import Path

import pytest

from aviato.core.declaration import Declaration
from aviato.core.errors import DeclarationError
from aviato.core.onboarding import materialize_items, plan_onboarding
from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT


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
