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


def test_settings_override_rejects_bare_list_restatement() -> None:
    # §4.2/§5.1 (FIX-2): a list-valued settings override (e.g. emptying `rulesets` or
    # `required_status_checks`) must be REJECTED, not silently accepted-and-ignored — list
    # properties need explicit add/remove, which the settings deep-merge doesn't provide.
    from aviato.paths import MODULE_SOURCE_ROOT

    registry = Registry(MODULE_SOURCE_ROOT)
    for bad in (
        {"settings": {"rulesets": []}},
        {"settings": {"default_branch": {"required_status_checks": ["x"]}}},
    ):
        with pytest.raises(CompositionError):
            resolve_profile(registry, "python-library", overrides=bad)
    # A non-list (scalar/map) settings override still works.
    resolved = resolve_profile(
        registry, "python-library", overrides={"settings": {"default_branch": {"required_reviews": 2}}}
    )
    assert resolved.settings["default_branch"]["required_reviews"] == 2


def test_unknown_settings_override_key_is_rejected_not_silently_dropped() -> None:
    # CX#4: a typo'd settings-override key (absent from the baseline schema) used to deep-merge in
    # then get silently filtered out at apply time — a silent no-op §4.2 forbids. Reject it.
    from aviato.paths import MODULE_SOURCE_ROOT

    registry = Registry(MODULE_SOURCE_ROOT)
    with pytest.raises(CompositionError):
        resolve_profile(registry, "python-library", overrides={"settings": {"default_branch": {"required_reveiws": 2}}})
    # A correctly-spelled baseline key still applies.
    ok = resolve_profile(
        registry, "python-library", overrides={"settings": {"default_branch": {"required_reviews": 2}}}
    )
    assert ok.settings["default_branch"]["required_reviews"] == 2


def test_version_source_locations_are_overridable() -> None:
    # CX#2/§12.3: the documented Swift override path must be real — a consumer overrides
    # version_source.locations for a real Xcode layout (the day-zero locations are a placeholder).
    from aviato.paths import MODULE_SOURCE_ROOT

    registry = Registry(MODULE_SOURCE_ROOT)
    overridden = resolve_profile(
        registry, "swift-app", overrides={"version_source": {"locations": ["App.xcodeproj/project.pbxproj"]}}
    )
    assert overridden.version_source.locations == ("App.xcodeproj/project.pbxproj",)
    # Malformed override (no locations list) and overriding a profile with no version_source fail loud.
    with pytest.raises(CompositionError):
        resolve_profile(registry, "swift-app", overrides={"version_source": {"locations": "nope"}})


def test_variable_spec_secret_required_are_strict_booleans() -> None:
    # R5-3/§6.6: bool("false") is truthy — a quoted `secret: "false"` must NOT flip a non-secret
    # optional variable into a required secret. Strict-bool: real bool or "true"/"false" only.
    from aviato.core.composition import _variable_spec

    assert _variable_spec({"name": "v", "type": "string", "secret": "false"}).secret is False
    assert _variable_spec({"name": "v", "type": "string", "required": "false"}).required is False
    with pytest.raises(CompositionError):
        _variable_spec({"name": "v", "type": "string", "secret": "maybe"})


def test_security_floor_enforced_against_profile_data_not_just_overrides(module_root: Path, tmp_path: Path) -> None:
    # R1-4/§2.13: a profile whose settings bundle omits/weakens the canonical security floor must be
    # rejected, not only a consumer override. Build a registry with a baseline floor + a profile
    # whose settings bundle drops it.
    import shutil

    import yaml as _yaml

    from aviato.paths import MODULE_SOURCE_ROOT

    root = tmp_path / "lib"
    shutil.copytree(MODULE_SOURCE_ROOT, root)
    # A settings bundle with NO security block, and a profile using it.
    (root / "bundles" / "settings" / "nosec.yaml").write_text(
        _yaml.safe_dump({"name": "nosec", "settings": {"default_branch": {"requires_pull_request": True}}}),
        encoding="utf-8",
    )
    (root / "nosec-prof.yaml").write_text(
        _yaml.safe_dump(
            {
                "name": "nosec-prof",
                "workflows": "python-library-wf",
                "scaffold": "python-library-sc",
                "settings": "nosec",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CompositionError) as exc:
        resolve_profile(Registry(root), "nosec-prof")
    assert "security" in str(exc.value).lower()


def test_settings_bundle_child_bare_list_is_rejected(module_root: Path) -> None:
    # R1-5/§4.2: a child settings bundle restating a list (e.g. emptying rulesets) silently replaces
    # the inherited list — settings have no add/remove, so reject it like a bare consumer override.
    bundles = module_root / "bundles" / "settings"
    (bundles / "base-set2.yaml").write_text(
        yaml.safe_dump({"name": "base-set2", "settings": {"rulesets": ["a", "b"]}}), encoding="utf-8"
    )
    (bundles / "child-set2.yaml").write_text(
        yaml.safe_dump({"name": "child-set2", "extends": "base-set2", "settings": {"rulesets": []}}), encoding="utf-8"
    )
    (module_root / "barelist-prof.yaml").write_text(
        yaml.safe_dump(
            {"name": "barelist-prof", "workflows": "child-wf", "scaffold": "child-sc", "settings": "child-set2"}
        ),
        encoding="utf-8",
    )
    with pytest.raises(CompositionError) as exc:
        resolve_profile(Registry(module_root), "barelist-prof")
    assert "rulesets" in str(exc.value)


def test_non_dict_security_override_is_clean_composition_error() -> None:
    # §2.13: replacing the security baseline with a non-mapping (e.g. `security: false`) is the
    # maximal weakening — it must fail with a clean CompositionError, never a TypeError crash.
    from aviato.paths import MODULE_SOURCE_ROOT

    registry = Registry(MODULE_SOURCE_ROOT)
    for bad in (False, None, "off", 0, []):
        with pytest.raises(CompositionError):
            resolve_profile(registry, "python-library", overrides={"settings": {"security": bad}})


def test_undeclared_pipeline_reference_is_hard_error() -> None:
    # §5.1: a referenced pipeline absent from the manifest is a typo and must hard-error, not
    # silently resolve to a module-less pipeline. Gated on a manifest existing (test registries
    # without one stay lenient).
    from aviato.paths import MODULE_SOURCE_ROOT

    registry = Registry(MODULE_SOURCE_ROOT)
    with pytest.raises(CompositionError):
        resolve_profile(registry, "python-library", overrides={"pipelines": {"add": ["bogus-pipeline"]}})


def test_undeclared_pipeline_check_is_lenient_without_manifest(module_root: Path) -> None:
    # A bare test registry with no pipelines.yaml declares no pipelines (declared_pipelines None);
    # composition stays lenient there, exactly as before — the check only bites a real manifest.
    assert Registry(module_root).declared_pipelines() is None
    resolve_profile(Registry(module_root), "child")  # references a/b/c with no manifest → no raise


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


def test_version_source_override_rejects_empty_or_nonstring_locations() -> None:
    # R5-10: an override whose `locations` is empty, or carries a non-string / blank entry, parses
    # but silently disables (or corrupts) the version-source downstream in version tooling (§12.3).
    # Composition must fail closed on each shape so the operator fixes it rather than getting a
    # no-op version bump.
    from aviato.paths import MODULE_SOURCE_ROOT

    registry = Registry(MODULE_SOURCE_ROOT)
    for bad in ([], [123], ["VERSION", 1], ["  "], [""]):
        with pytest.raises(CompositionError):
            resolve_profile(registry, "swift-app", overrides={"version_source": {"locations": bad}})
    # A boolean is an int subclass but not a str → still rejected (not silently coerced).
    with pytest.raises(CompositionError):
        resolve_profile(registry, "swift-app", overrides={"version_source": {"locations": [True]}})


def test_scalar_default_branch_override_raises_composition_error() -> None:
    # R2-3-1: a scalar (non-mapping) default_branch settings override must fail as a CompositionError,
    # not a raw ValueError from dict(<scalar>) that escapes the fleet-scan AviatoError guard.
    from aviato.paths import MODULE_SOURCE_ROOT

    registry = Registry(MODULE_SOURCE_ROOT)
    with pytest.raises(CompositionError):
        resolve_profile(registry, "python-library", overrides={"settings": {"default_branch": "develop"}})


def test_profile_declared_version_source_locations_validated_like_override() -> None:
    # R2-1-VS: the profile-declared version_source uses the SAME validation as a consumer override
    # (parity) — empty/blank/non-string/non-mapping all rejected, so a profile can't silently no-op
    # the version bump. Exercise the shared helper directly (a full minimal registry just to reach
    # it is needless scaffolding).
    from aviato.core.composition import _validated_locations

    assert _validated_locations({"locations": ["VERSION"]}, context="x") == ("VERSION",)
    for bad in (
        {},
        {"locations": []},
        {"locations": [123]},
        {"locations": ["  "]},
        {"locations": [True]},
        "scalar",
        None,
    ):
        with pytest.raises(CompositionError):
            _validated_locations(bad, context="x")


def test_validated_locations_rejects_paths_that_escape_root() -> None:
    # R9-15: an absolute path or a `..` component would let `aviato bump-version` write outside the
    # repo checkout during a release. Reject them; a normal repo-relative path is accepted.
    from aviato.core.composition import _validated_locations
    from aviato.core.errors import CompositionError

    for bad in (["/etc/x"], ["../x"], ["a/../../b"]):
        with pytest.raises(CompositionError):
            _validated_locations({"locations": bad}, context="x")
    assert _validated_locations({"locations": ["pyproject.toml", "src/_version.py"]}, context="x") == (
        "pyproject.toml",
        "src/_version.py",
    )


def test_pipelines_override_present_null_does_not_raise_typeerror() -> None:
    # R9-16: a present-null `add:`/`remove:` must be a clean no-op (not a raw TypeError that aborts a
    # fleet scan); a non-list value is a clean CompositionError.
    from aviato.core.composition import _override_pipeline_list
    from aviato.core.errors import CompositionError

    assert _override_pipeline_list(None, "add") == ()
    assert _override_pipeline_list(["ci"], "remove") == ("ci",)
    with pytest.raises(CompositionError):
        _override_pipeline_list("ci", "add")


def test_template_module_path_is_confined() -> None:
    # N6: a template module's output_path/source must be repo-relative — reject absolute / `..`
    # so a malformed library module cannot make scaffold reads/writes escape the trees.
    from aviato.core.errors import CompositionError
    from aviato.core.registry import _confined_relpath

    for bad in ("/etc/x", "../../x", "a/../../b"):
        with pytest.raises(CompositionError):
            _confined_relpath(bad, "output_path")
    assert _confined_relpath(".github/workflows/aviato-ci.yml", "output_path") == ".github/workflows/aviato-ci.yml"
