from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aviato.core.composition import resolve_profile
from aviato.core.errors import CompositionError
from aviato.core.model import VersionSourceModule
from aviato.core.registry import Registry


def test_resolve_applies_extends_add_remove_for_lists(module_root: Path) -> None:
    rs = resolve_profile(Registry(module_root), "child")
    assert rs.pipelines == ("b", "c")


def test_resolve_deep_merges_settings_maps(module_root: Path) -> None:
    rs = resolve_profile(Registry(module_root), "child")
    # leaf overridden, sibling preserved
    assert rs.settings["pr"]["required_reviews"] == 1
    assert rs.settings["pr"]["dismiss_stale"] is True


def test_resolve_includes_variables_version_source_toolchain(module_root: Path) -> None:
    rs = resolve_profile(Registry(module_root), "child")
    assert rs.variables[0].name == "dist"
    assert rs.version_source == VersionSourceModule(locations=("pyproject.toml",))
    assert rs.toolchain == {"engine": "x"}


def test_resolve_resolves_template_refs_to_modules(module_root: Path) -> None:
    rs = resolve_profile(Registry(module_root), "child")
    assert [t.output_path for t in rs.templates] == ["cfg.py"]


def test_consumer_overrides_apply_same_semantics(module_root: Path) -> None:
    rs = resolve_profile(
        Registry(module_root),
        "child",
        overrides={"settings": {"pr": {"required_reviews": 0}}, "pipelines": {"add": ["d"]}},
    )
    assert rs.settings["pr"]["required_reviews"] == 0
    assert "d" in rs.pipelines


def test_resolution_is_pure_deterministic(module_root: Path) -> None:
    reg = Registry(module_root)
    assert resolve_profile(reg, "child") == resolve_profile(reg, "child")


def test_docs_opt_in_adds_docs_pipeline(module_root: Path) -> None:
    reg = Registry(module_root)
    without = resolve_profile(reg, "child")
    with_docs = resolve_profile(reg, "child", docs=True)
    assert "docs-pages" not in without.pipelines  # default off
    assert "docs-pages" in with_docs.pipelines


def test_docs_pipeline_not_duplicated_if_already_present(module_root: Path) -> None:
    reg = Registry(module_root)
    rs = resolve_profile(reg, "child", docs=True, overrides={"pipelines": {"add": ["docs-pages"]}})
    assert rs.pipelines.count("docs-pages") == 1


def test_missing_referenced_module_is_hard_error(module_root: Path) -> None:
    # point a profile at a non-existent workflows bundle
    (module_root / "broken.yaml").write_text(
        yaml.safe_dump({"name": "broken", "workflows": "ghost", "scaffold": "child-sc", "settings": "child-set"}),
        encoding="utf-8",
    )
    with pytest.raises(CompositionError):
        resolve_profile(Registry(module_root), "broken")


def test_bare_list_under_extends_is_rejected(module_root: Path) -> None:
    # a child bundle that restates `pipelines` while also extending is a bare-list replacement
    (module_root / "bundles" / "workflows" / "bare.yaml").write_text(
        yaml.safe_dump({"name": "bare", "extends": "base-wf", "pipelines": ["z"]}),
        encoding="utf-8",
    )
    (module_root / "bareprof.yaml").write_text(
        yaml.safe_dump({"name": "bareprof", "workflows": "bare", "scaffold": "child-sc", "settings": "child-set"}),
        encoding="utf-8",
    )
    with pytest.raises(CompositionError):
        resolve_profile(Registry(module_root), "bareprof")
