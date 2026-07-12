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
        profile_identity="aviato-profile/child/v1",
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


def test_repin_warns_on_exact_to_floating_major_downgrade(module_root: Path) -> None:
    # review #21: moving from exact 1.5.0 down to floating "1" (floor 1.0.0) is a real backward
    # move; the old major-only fallback compared 1<1 and missed it. Now both sides floor to a
    # comparable lower bound so (1,0,0) < (1,5,0) is correctly flagged.
    plan = plan_repin(Registry(module_root), _decl(version="1.5.0"), "1")
    assert plan.downgrade_warning is not None
    # Exact 1.0.0 → floating "1" is NOT a downgrade (floating 1 tracks >= 1.0.0).
    assert plan_repin(Registry(module_root), _decl(version="1.0.0"), "1").downgrade_warning is None


def test_repin_reports_orphaned_override(module_root: Path) -> None:
    decl = _decl(overrides={"settings": {"nonexistent_key": 1}})
    plan = plan_repin(Registry(module_root), decl, "v1.0.0")
    assert "nonexistent_key" in plan.orphaned_overrides
    # R1-8: orphaned overrides are BLOCKING — composition now hard-rejects them on re-sync, so a
    # write-then-sync would half-apply. The plan must NOT be ok.
    assert plan.ok is False


def test_repin_reports_orphaned_pipeline_override(module_root: Path) -> None:
    # §5.12: a consumer pipeline override that removes a pipeline no longer present at
    # the target must be REPORTED as orphaned, not crash the plan with a §4.2
    # remove-of-absent CompositionError (which would make a clean re-pin un-plannable).
    decl = _decl(overrides={"pipelines": {"remove": ["ghost-pipeline"]}})
    plan = plan_repin(Registry(module_root), decl, "v1.0.0")
    assert "ghost-pipeline" in plan.orphaned_overrides


def test_repin_flags_pipeline_add_that_collides_at_target(module_root: Path) -> None:
    # §5.12/§4.2: a consumer pipelines.add of a pipeline that the target version now BUNDLES
    # collides (add-of-already-present). plan_repin must surface this at PLAN time and block
    # the re-pin — not pass as ok and let the next `aviato sync` crash with CompositionError.
    # The child profile resolves to pipelines [b, c]; adding 'c' collides with the base set.
    decl = _decl(overrides={"pipelines": {"add": ["c"]}})
    plan = plan_repin(Registry(module_root), decl, "v1.0.0")
    assert plan.ok is False
    assert "c" in plan.conflicting_overrides


def test_repin_allows_profile_evolution_at_target(module_root: Path, tmp_path: Path) -> None:
    # §5.12/§6.5: a profile NAME is a stable public identity. If the same name maps to a
    # different composition at the target version (here: its version-source artifact kind
    # changed), it has been repurposed → refuse, like "profile no longer exists".
    import shutil

    import yaml

    target = tmp_path / "target-modsrc"
    shutil.copytree(module_root, target)
    child = target / "child.yaml"
    doc = yaml.safe_load(child.read_text())
    doc["version_source"] = {"locations": ["package.json"]}
    doc["variables"].append({"name": "optional", "type": "string", "required": False})
    child.write_text(yaml.safe_dump(doc, sort_keys=False))

    assert plan_repin(Registry(module_root), _decl(), "v2.0.0", target_registry=Registry(target)).ok


def test_repin_refuses_when_profile_identity_changes_at_target(module_root: Path, tmp_path: Path) -> None:
    import shutil

    import yaml

    target = tmp_path / "target-modsrc"
    shutil.copytree(module_root, target)
    child = target / "child.yaml"
    doc = yaml.safe_load(child.read_text())
    doc["identity"] = "aviato-profile/repurposed/v1"
    child.write_text(yaml.safe_dump(doc, sort_keys=False))

    with pytest.raises(CompositionError):
        plan_repin(Registry(module_root), _decl(), "v2.0.0", target_registry=Registry(target))


def test_repin_legacy_declaration_requires_sync_first(module_root: Path) -> None:
    declaration = _decl()
    declaration.profile_identity = None
    with pytest.raises(CompositionError, match=r"sync.*current pin"):
        plan_repin(Registry(module_root), declaration, "2", target_registry=Registry(module_root))
