from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from aviato.core.composition import _resolve_list, _variable_spec, resolve_profile
from aviato.core.errors import CompositionError
from aviato.core.model import VersionSourceModule
from aviato.core.registry import Registry


def test_resolve_applies_extends_add_remove_for_lists(module_root: Path) -> None:
    rs = resolve_profile(Registry(module_root), "child")
    assert rs.pipelines == ("b", "c")


def test_resolve_list_rejects_add_remove_on_resolution_root() -> None:
    # §4.2: add/remove are relative to a base layer; the resolution root IS the base,
    # so add/remove on it have no meaning. Silently ignoring them would let a data
    # author's misplaced ``add:`` become a no-op. Fail loud instead.
    root = SimpleNamespace(name="root", extends=None, pipelines=("a",), add=("b",), remove=())
    with pytest.raises(CompositionError):
        _resolve_list([root], "pipelines")


def test_always_on_security_baseline_cannot_be_composed_away() -> None:
    # §2.13: there is NO composition that silently omits security scanning. The
    # baseline pipeline is data-flagged always_on, and resolution refuses to drop it.
    from aviato.paths import MODULE_SOURCE_ROOT

    registry = Registry(MODULE_SOURCE_ROOT)
    resolved = resolve_profile(registry, "python-library")
    assert "security-baseline" in resolved.pipelines
    with pytest.raises(CompositionError):
        resolve_profile(registry, "python-library", overrides={"pipelines": {"remove": ["security-baseline"]}})


def test_security_baseline_toggles_cannot_be_weakened_by_override() -> None:
    # §2.13: the baseline is not just the always-on PIPELINE — the repo security toggles
    # (secret scanning, push protection, dependency scanning) are desired-state in the
    # settings baseline, and a consumer override must not be able to silently disable
    # them via the settings deep-merge. Each disable is a hard composition error.
    from aviato.paths import MODULE_SOURCE_ROOT

    registry = Registry(MODULE_SOURCE_ROOT)
    baseline = resolve_profile(registry, "python-library").settings.get("security", {})
    assert baseline, "expected a non-empty security baseline to protect"
    for key in baseline:
        with pytest.raises(CompositionError):
            resolve_profile(registry, "python-library", overrides={"settings": {"security": {key: False}}})


def test_security_baseline_override_may_strengthen_or_leave_unchanged() -> None:
    # A no-op or strengthening override is allowed; only weakening/removal is refused (§2.13).
    from aviato.paths import MODULE_SOURCE_ROOT

    registry = Registry(MODULE_SOURCE_ROOT)
    baseline = resolve_profile(registry, "python-library").settings.get("security", {})
    same = {key: value for key, value in baseline.items()}  # re-asserting the same values
    resolved = resolve_profile(registry, "python-library", overrides={"settings": {"security": same}})
    assert resolved.settings["security"] == baseline


def test_variable_spec_rejects_unknown_type() -> None:
    # §6.6: a typo'd type (e.g. "bool") must fail loud, never silently render uncoerced.
    with pytest.raises(CompositionError):
        _variable_spec({"name": "flag", "type": "bool"})


def test_variable_spec_enum_requires_domain() -> None:
    # §6.6: an enum with no domain could never resolve any value (incl. its default).
    with pytest.raises(CompositionError):
        _variable_spec({"name": "variant", "type": "enum"})


def test_variable_spec_accepts_valid_kinds() -> None:
    assert _variable_spec({"name": "s", "type": "string"}).type == "string"
    assert _variable_spec({"name": "b", "type": "boolean"}).type == "boolean"
    spec = _variable_spec({"name": "v", "type": "enum", "domain": ["a", "b"]})
    assert spec.domain == ("a", "b")


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


def test_unknown_override_key_is_rejected(module_root: Path) -> None:
    # §4.2: override application is explicit, never silent. A typo'd or unsupported
    # override key must be a hard error, not silently dropped.
    with pytest.raises(CompositionError):
        resolve_profile(
            Registry(module_root),
            "child",
            overrides={"setting": {"pr": {"required_reviews": 0}}},
        )


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
