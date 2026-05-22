from __future__ import annotations

from pathlib import Path

import pytest

from aviato.core.declaration import Declaration
from aviato.core.errors import CompositionError
from aviato.core.registry import Registry
from aviato.core.repin import plan_repin

_DEFAULT_VARS = {"dist": "x"}


def _decl(version: str = "v1", variables=None, overrides=None) -> Declaration:
    return Declaration(
        profile="child",
        version=version,
        variables=_DEFAULT_VARS if variables is None else variables,
        overrides=overrides or {},
    )


def test_repin_ok_when_profile_exists_and_vars_present(module_root: Path) -> None:
    plan = plan_repin(Registry(module_root), _decl(), "v1.0.0")
    assert plan.ok is True
    assert plan.newly_required == []


def test_repin_refuses_when_profile_absent(module_root: Path) -> None:
    decl = Declaration(profile="ghost", version="v1", variables={})
    with pytest.raises(CompositionError):
        plan_repin(Registry(module_root), decl, "v2.0.0")


def test_repin_flags_newly_required_variable(module_root: Path) -> None:
    # declaration omits the required 'dist' variable
    plan = plan_repin(Registry(module_root), _decl(variables={}), "v1.0.0")
    assert plan.ok is False
    assert "dist" in plan.newly_required


def test_repin_warns_on_downgrade(module_root: Path) -> None:
    plan = plan_repin(Registry(module_root), _decl(version="v2.0.0"), "v1.0.0")
    assert plan.downgrade_warning is not None
    assert "backward" in plan.downgrade_warning.lower()


def test_repin_no_downgrade_warning_on_upgrade(module_root: Path) -> None:
    plan = plan_repin(Registry(module_root), _decl(version="v1.0.0"), "v2.0.0")
    assert plan.downgrade_warning is None


def test_repin_reports_orphaned_override(module_root: Path) -> None:
    decl = _decl(overrides={"settings": {"nonexistent_key": 1}})
    plan = plan_repin(Registry(module_root), decl, "v1.0.0")
    assert "nonexistent_key" in plan.orphaned_overrides
