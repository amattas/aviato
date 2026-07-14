from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import PurePosixPath
from typing import Any

from .errors import CompositionError
from .listmerge import merge_list
from .mapmerge import deep_merge
from .model import (
    ResolvedSet,
    ScaffoldBundle,
    SettingsBundle,
    VariableSpec,
    VersionSourceModule,
    WorkflowsBundle,
    deep_thaw,
)
from .registry import Registry
from .settingsdrift import weakens

_VARIABLE_TYPES = {"string", "boolean", "enum"}


def _variable_spec(item: dict[str, Any]) -> VariableSpec:
    """Build a typed VariableSpec, validating the §6.6 schema at composition time.

    The variable ``type`` must be one of string/boolean/enum (a typo like ``bool``
    must fail loud here, never silently render uncoerced), and an ``enum`` must
    declare a non-empty ``domain`` (otherwise no value — including its own default —
    could ever resolve, §6.6).
    """
    name = item.get("name")
    var_type = item.get("type")
    if var_type not in _VARIABLE_TYPES:
        raise CompositionError(
            f"variable {name!r} has unknown type {var_type!r}; must be one of {sorted(_VARIABLE_TYPES)} (§6.6)"
        )
    domain = tuple(item["domain"]) if item.get("domain") is not None else None
    if var_type == "enum" and not domain:
        raise CompositionError(f"enum variable {name!r} must declare a non-empty domain (§6.6)")
    return VariableSpec(
        name=item["name"],
        type=var_type,
        secret=_spec_bool(item.get("secret", False), "secret", name),
        required=_spec_bool(item.get("required", True), "required", name),
        domain=domain,
        default=item.get("default"),
    )


def _spec_bool(value: object, field: str, varname: object) -> bool:
    """Strictly coerce a variable-spec boolean field (§6.6, R5-3).

    `bool("false")` is truthy, so a quoted `secret: "false"` in module data would flip a
    non-secret optional variable into a REQUIRED SECRET. Accept only a real bool or the
    case-insensitive strings ``true``/``false``; anything else fails loud at composition time.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise CompositionError(f"variable {varname!r} field {field!r} must be a boolean, got {value!r} (§6.6)")


def _validated_locations(vs: object, *, context: str) -> tuple[str, ...]:
    """Validate a ``version_source`` mapping's ``locations`` (§12.3, R5-10/R2-1-VS).

    Accept only a mapping carrying a non-empty list of non-blank path strings — the same rule for
    a profile-declared value and a consumer override, so neither can silently disable the
    version-source (empty list / `{}`) or feed a bogus path (non-string/blank entry) into version
    tooling. (`bool` is an int subclass but not a str, so it is correctly rejected.)
    """
    if not isinstance(vs, dict):
        raise CompositionError(f"{context} must be a mapping with a 'locations' list (§12.3)")
    locations = vs.get("locations")
    if (
        not isinstance(locations, list)
        or not locations
        or any(not isinstance(p, str) or not p.strip() for p in locations)
    ):
        raise CompositionError(
            f"{context} 'locations' must be a non-empty list of non-blank path strings (§12.3) — "
            f"e.g. version_source: {{locations: ['path/to/your/version-file']}}"
        )
    # R9-15: confine to the consumer repo. An absolute path or a `..` component would let
    # `aviato bump-version` (run during the release workflow) write OUTSIDE the checkout. The
    # version-source is always a repo-relative path; reject anything that can escape root.
    for p in locations:
        pure = PurePosixPath(p)
        if pure.is_absolute() or p.startswith("\\") or ".." in pure.parts:
            raise CompositionError(
                f"{context} 'locations' must be repo-relative paths without '..' (§12.3); "
                f"refusing {p!r} (it could write outside the repository)"
            )
    return tuple(locations)


def _override_pipeline_list(value: object, field: str) -> tuple[str, ...]:
    """Validate a ``pipelines`` override's ``add``/``remove`` (R9-16).

    A PRESENT-but-null (`add:` with no value → ``None``) or absent key is an empty no-op. Anything
    else must be a list of non-blank strings — without this guard a present-null fed ``None`` into
    ``merge_list``'s ``list(add)``, raising a raw ``TypeError`` that escaped ``scan_fleet``'s
    AviatoError guard and aborted the operator's whole fleet scan (§5.11).
    """
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise CompositionError(f"pipelines override {field!r} must be a list of non-blank strings (§4.2)")
    return tuple(value)


def _settings_override_lists(override: dict[str, Any], _prefix: str = "") -> list[str]:
    """Dotted paths of any list-valued key in a settings override (§4.2 bare-list guard).

    Recurses nested maps; a list value at any depth is a bare-list restatement the settings
    deep-merge would silently replace, which §4.2 forbids (lists need explicit add/remove).
    """
    found: list[str] = []
    for key, value in override.items():
        path = f"{_prefix}{key}"
        if isinstance(value, list):
            found.append(path)
        elif isinstance(value, dict):
            found.extend(_settings_override_lists(value, f"{path}."))
    return found


def _unknown_settings_override_paths(
    override: Mapping[str, Any], baseline: Mapping[str, Any], _prefix: str = ""
) -> list[str]:
    """Dotted paths in a settings override that are absent from the baseline schema (§4.2, CX#4).

    The composed baseline is the authoritative schema of managed settings — every reconcilable key
    appears in it. A consumer override key NOT present in the baseline is a typo (e.g.
    ``required_reveiws``) that the deep-merge would accept and the apply path then silently drop,
    so it is rejected here rather than becoming a silent no-op. Recurses only where the baseline
    also nests a map (so a leaf override of a known key is fine); list values are handled by the
    separate bare-list guard.
    """
    unknown: list[str] = []
    for key, value in override.items():
        path = f"{_prefix}{key}"
        if key not in baseline:
            unknown.append(path)
        elif isinstance(value, Mapping) and isinstance(baseline.get(key), Mapping):
            unknown.extend(_unknown_settings_override_paths(value, baseline[key], f"{path}."))
    return unknown


def _leaf_type(value: object) -> str:
    """A coarse type name for settings-leaf validation. ``bool`` is checked BEFORE ``int`` because
    ``isinstance(True, int)`` is True at runtime — a bool is not an acceptable required-reviews int, nor
    an int an acceptable boolean toggle."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _validate_settings_leaf_types(baseline: dict[str, Any], resolved: dict[str, Any], block: str) -> None:
    """Reject an override that changed a managed leaf's TYPE or removed it (N1, §2.9/§5.7).

    Every key the baseline declares must survive resolution with the SAME coarse type. A string where a
    bool/int is expected (`required_reviews: "NaN"` → `int()` crashes the apply; `block_force_push:
    "false"` → truthy → force-push protection INVERTED), a null that drops a key, or a list/dict where a
    scalar belongs are all rejected here — at resolve time, before any privileged write.
    """
    if not isinstance(resolved, dict):
        raise CompositionError(
            f"settings override replaced the managed {block} block with a non-mapping ({resolved!r}) "
            "(§4.2/§2.13); it cannot be disabled or retyped wholesale"
        )
    for key, base_value in baseline.items():
        if key not in resolved:
            raise CompositionError(
                f"settings override removed managed {block} key {key!r} (§2.9); a dropped protection "
                "key would silently weaken the apply — keep the baseline key or override its value"
            )
        if _leaf_type(resolved[key]) != _leaf_type(base_value):
            raise CompositionError(
                f"settings override set {block}.{key} to a {_leaf_type(resolved[key])} "
                f"({resolved[key]!r}); the managed type is {_leaf_type(base_value)} — a mismatched type "
                "would crash or silently invert the privileged apply (N1, §2.9)"
            )


def _chain(load: Callable[[str], Any], name: str) -> list[Any]:
    """Walk an ``extends`` chain from ``name`` to its root, root-first.

    ``load`` maps a bundle name to its dataclass. Ancestors resolve before
    descendants (§4.2 deterministic ordering).
    """
    layers: list[Any] = []
    seen: set[str] = set()
    current: str | None = name
    while current is not None:
        if current in seen:
            raise CompositionError(f"cyclic extends chain at {current!r}")
        seen.add(current)
        bundle = load(current)
        layers.append(bundle)
        current = bundle.extends
    layers.reverse()
    return layers


def _resolve_list(layers: list[Any], base_attr: str) -> tuple[str, ...]:
    root = layers[0]
    if root.extends is not None:  # defensive; root by construction has no extends
        raise CompositionError(f"resolution root {root.name!r} unexpectedly extends another")
    if root.add or root.remove:
        # add/remove are relative to a base layer; the root IS the base, so they have no
        # meaning here. Silently ignoring them would let a misplaced override no-op (§4.2).
        raise CompositionError(
            f"resolution root {root.name!r} declares add/remove, which only apply under extends (§4.2)"
        )
    resolved = list(getattr(root, base_attr))
    for layer in layers[1:]:
        if getattr(layer, base_attr):
            raise CompositionError(
                f"bundle {layer.name!r} restates a bare {base_attr} list under extends; use add/remove (§4.2)"
            )
        resolved = merge_list(resolved, add=layer.add, remove=layer.remove)
    return tuple(resolved)


def _resolve_settings(layers: list[SettingsBundle]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for index, layer in enumerate(layers):
        # R1-5/§4.2: settings are deep-merged maps with no add/remove semantics, so a list value at
        # any depth in a NON-root (extending) bundle layer would silently REPLACE the inherited list
        # (e.g. emptying `rulesets`/`required_status_checks`) — the same bare-list hazard the consumer
        # override path already rejects. Only the root layer (the base) may declare list values.
        if index > 0:
            bare = _settings_override_lists(deep_thaw(layer.settings))
            if bare:
                raise CompositionError(
                    f"settings bundle {layer.name!r} restates list-valued key(s) {sorted(bare)} "
                    f"under extends; settings lists are base-only and cannot be replaced by a child "
                    f"bundle (§4.2)"
                )
        resolved = deep_merge(resolved, deep_thaw(layer.settings))
    return resolved


def resolve_profile(
    registry: Registry,
    name: str,
    *,
    overrides: dict[str, Any] | None = None,
    docs: bool = False,
) -> ResolvedSet:
    """Resolve a profile to a fully-composed convention set (§5.1).

    Pure and deterministic: it reads only the registry's declarative data,
    applies ``extends`` + add/remove for lists (§4.2 edge rules) and deep-merge
    for the settings map, then applies consumer ``overrides`` under the same
    semantics. When ``docs`` is true (the §6.1 opt-in), the profile's declared
    documentation deploy pipeline (§13.3) is composed on top — the pipeline name
    is plug-in data (``docs_pipeline``), never a core literal. Raises
    :class:`CompositionError` on a missing module, a bare list under
    ``extends``/override, or an add/remove edge violation.
    """
    overrides = overrides or {}
    unknown = set(overrides) - {"pipelines", "settings", "version_source"}
    if unknown:
        raise CompositionError(
            f"unknown override key(s) {sorted(unknown)}; only 'pipelines', 'settings', and "
            f"'version_source' are supported (§4.2 — overrides are explicit, never silently dropped)"
        )
    profile = registry.profile(name)

    wf_layers: list[WorkflowsBundle] = _chain(registry.workflows_bundle, profile.workflows)
    pipelines = _resolve_list(wf_layers, "pipelines")

    sc_layers: list[ScaffoldBundle] = _chain(registry.scaffold_bundle, profile.scaffold)
    template_refs = _resolve_list(sc_layers, "templates")

    set_layers: list[SettingsBundle] = _chain(registry.settings_bundle, profile.settings)
    settings = _resolve_settings(set_layers)
    # Capture the always-on security baseline BEFORE consumer overrides apply (§2.13).
    # Which toggles are baseline is DATA (the settings bundle's ``security`` block), so
    # the core names no specific scanner; it only enforces that the composed baseline
    # cannot be silently omitted or weakened by an override below.
    baseline_security = dict(settings.get("security", {}))
    # N1 (§5.7/§2.9): also capture the branch-protection baseline so a consumer override that changes a
    # leaf's TYPE (`required_reviews: "NaN"`, `block_force_push: "false"`) — which would crash the apply
    # (`int("NaN")`) or silently INVERT protection (a non-empty string is truthy) — is rejected at
    # resolve time, not discovered at the privileged write.
    baseline_default_branch = dict(settings.get("default_branch", {}))

    pipeline_override = overrides.get("pipelines")
    if pipeline_override is not None:
        if not isinstance(pipeline_override, dict):
            raise CompositionError("pipelines override must use add/remove, not a bare list (§4.2)")
        pipelines = tuple(
            merge_list(
                list(pipelines),
                add=_override_pipeline_list(pipeline_override.get("add"), "add"),
                remove=_override_pipeline_list(pipeline_override.get("remove"), "remove"),
            )
        )

    settings_override = overrides.get("settings")
    if settings_override is not None:
        if not isinstance(settings_override, dict):
            raise CompositionError("settings override must be a mapping (§4.2)")
        # §4.2/§5.1: a list-valued property is modified by EXPLICIT add/remove only — a child must
        # never restate a bare list (which would silently replace, e.g. emptying `rulesets` or
        # `required_status_checks`). Settings overrides are map deep-merges with no add/remove
        # semantics, so a bare list in the override is rejected rather than silently accepted-and-
        # ignored (the actual ruleset apply/drift derive from the manifest + composed checks, so a
        # replaced list would have no effect — a silent no-op the spec forbids).
        bare_lists = _settings_override_lists(settings_override)
        if bare_lists:
            raise CompositionError(
                f"settings override restates list-valued key(s) {sorted(bare_lists)} as a bare list "
                "(§4.2); list-valued settings are not consumer-overridable via a bare list — they "
                "are derived from the composed pipelines (status checks) and the ruleset manifest"
            )
        # CX#4: a settings-override key absent from the composed baseline schema is a typo (e.g.
        # `required_reveiws`) the deep-merge would accept and the apply path then silently drop.
        # Reject it — §4.2 overrides are explicit, never a silent no-op. (The baseline carries every
        # reconcilable key, so a legitimate override is never wrongly rejected.)
        unknown_keys = _unknown_settings_override_paths(settings_override, settings)
        if unknown_keys:
            raise CompositionError(
                f"settings override has unknown key(s) {sorted(unknown_keys)} not present in the "
                "managed settings baseline (§4.2) — likely a typo; it would be silently dropped at "
                "apply time. Use an exact baseline key."
            )
        settings = deep_merge(settings, settings_override)
        # N1: every managed leaf must keep its baseline TYPE and stay present — a string/null where a
        # bool/int/list is expected would crash or silently invert the apply (§2.9). Validate the
        # branch-protection and security blocks against the baseline shape.
        _validate_settings_leaf_types(baseline_default_branch, settings.get("default_branch", {}), "default_branch")
        _validate_settings_leaf_types(baseline_security, settings.get("security", {}), "security")
        # §2.13: the security baseline is always-on — "there is no composition that
        # silently omits it." An override may strengthen a toggle but may never remove
        # or weaken one (true→false, etc.); doing so is a hard composition error, the
        # settings analogue of the always_on_pipelines guard below.
        resolved_security = settings.get("security", {})
        if not isinstance(resolved_security, dict):
            # A non-dict override (e.g. ``security: false``) replaces the whole baseline block
            # wholesale — the maximal weakening. Treat it as a clean refusal, not a TypeError.
            raise CompositionError(
                "consumer override replaces the always-on security baseline with a non-mapping "
                f"({resolved_security!r}); the security baseline cannot be disabled (§2.13)"
            )
        weakened = [
            key
            for key, base_value in baseline_security.items()
            if key not in resolved_security or weakens(base_value, resolved_security[key])
        ]
        if weakened:
            raise CompositionError(
                f"consumer override weakens or removes always-on security baseline "
                f"setting(s) {sorted(weakened)} (§2.13); the security baseline cannot be "
                "disabled or weakened via a profile or consumer override"
            )

    # R1-4/§2.13: the prior guard only stops a CONSUMER OVERRIDE from weakening the profile's own
    # security block — it can't catch a PROFILE/BUNDLE that omits or weakens security in the first
    # place (`baseline_security` is captured from the profile's own resolved settings). Enforce the
    # canonical always-on security floor (DATA: the `baseline` bundle's security) against the FINAL
    # resolved settings, so "no composition silently omits security" holds for profile data too, not
    # just overrides. Skipped when the registry declares no floor (a bare test registry).
    floor = registry.security_floor()
    if floor:
        resolved_security = settings.get("security", {})
        if not isinstance(resolved_security, dict):
            raise CompositionError(
                f"profile {name!r} composes a non-mapping security block ({resolved_security!r}); "
                "the always-on security baseline cannot be disabled (§2.13)"
            )
        below_floor = [
            key
            for key, floor_value in floor.items()
            if key not in resolved_security or weakens(floor_value, resolved_security[key])
        ]
        if below_floor:
            raise CompositionError(
                f"profile {name!r} omits or weakens always-on security baseline setting(s) "
                f"{sorted(below_floor)} relative to the canonical floor (§2.13); every profile must "
                "compose at least the baseline security toggles"
            )

    doc = registry.profile_doc(name)

    if docs:
        docs_pipeline = doc.get("docs_pipeline")
        if docs_pipeline and docs_pipeline not in pipelines:
            pipelines = (*pipelines, docs_pipeline)

    # §5.1: a referenced pipeline that the manifest does not declare is a hard error — a typo
    # must fail loud, never silently resolve to a module-less pipeline (no privileges/checks).
    # Gated on a manifest existing: a bare test/empty registry (declared_pipelines() is None)
    # declares no pipelines and stays lenient, exactly as before.
    declared = registry.declared_pipelines()
    if declared is not None:
        undeclared = sorted(ref for ref in pipelines if ref not in declared)
        if undeclared:
            raise CompositionError(
                f"profile {name!r} references undeclared pipeline(s) {undeclared}; every pipeline must be "
                f"declared in the pipelines manifest (§5.1) — check for a typo or a missing declaration"
            )

    # §2.13: no composition (profile or consumer override) may drop an always-on
    # pipeline (e.g. the security baseline). Which pipelines are mandatory is plug-in
    # DATA (``always_on`` in pipelines.yaml), so the core names no specific capability.
    dropped = [name for name in registry.always_on_pipelines() if name not in pipelines]
    if dropped:
        raise CompositionError(
            f"composition drops always-on pipeline(s) {sorted(dropped)} that must be present in "
            f"every Aviato-managed repository (§2.13); they cannot be removed via profile or override"
        )
    variables = tuple(_variable_spec(item) for item in doc.get("variables", []))
    # R5-10/R2-1-VS: `locations` (empty, or with a non-string/blank entry) parses but silently
    # disables the version-source (or feeds a bogus path) downstream in version tooling (§12.1).
    # Validate the SAME way for the profile-declared value AND the consumer override — fail closed
    # so the operator fixes it rather than getting a no-op bump. (`bool` is an int subclass but not
    # a str, so it is correctly rejected.)
    vs_doc = doc.get("version_source")
    version_source = (
        VersionSourceModule(locations=_validated_locations(vs_doc, context=f"profile {name!r} version_source"))
        if vs_doc is not None
        else None
    )
    # CX#2/§12.3: a consumer may OVERRIDE version_source.locations in its declaration — the
    # documented path when a profile's day-zero placeholder locations do not match the project's
    # actual layout. `locations` is config data (WHERE the version is written), not a composed
    # module list, so the override REPLACES it (an explicit operator choice, §4.2) rather than
    # using add/remove. Only valid when the profile actually declares a version_source. (No
    # language/target identifier appears here — the example path is generic — to keep core agnostic.)
    vs_override = overrides.get("version_source")
    if vs_override is not None:
        if version_source is None:
            raise CompositionError(f"profile {name!r} declares no version_source, so it cannot be overridden (§12.3)")
        version_source = VersionSourceModule(
            locations=_validated_locations(vs_override, context="version_source override")
        )
    toolchain = dict(doc.get("toolchain", {}))

    # Resolve each pipeline reference to its typed module (privileges/inputs/
    # secrets/runner, §3.2/§11.3). Undeclared pipelines (e.g. in a test registry)
    # are simply absent from pipeline_modules.
    pipeline_modules = tuple(module for ref in pipelines if (module := registry.pipeline_module(ref)) is not None)

    # Workflow schema v2 pipelines own non-workflow TemplateModule references. The
    # final scaffold is the stable union of the bundle base and the selected graph;
    # removing the last pipeline owner therefore removes its artifact without a
    # target-specific branch in core.
    pipeline_template_refs = tuple(ref for module in pipeline_modules for ref in module.artifacts)
    selected_template_refs = tuple(dict.fromkeys((*template_refs, *pipeline_template_refs)))
    templates = tuple(registry.template_module(ref) for ref in selected_template_refs)
    scaffold_templates = tuple(registry.template_module(ref) for ref in template_refs)

    # §10/#5: the merge gate must require exactly the checks the profile's composed
    # pipelines produce. Union the per-pipeline status_check contexts (e.g. the
    # language verify job) into the desired branch protection — single source of
    # truth, so a profile cannot require a check it never runs (or omit one it does).
    if profile.workflow_schema == 2:
        status_checks = sorted(
            {job.status_check for module in pipeline_modules for job in module.jobs if job.status_check}
        )
    else:
        status_checks = sorted({module.status_check for module in pipeline_modules if module.status_check})
    if status_checks or profile.workflow_schema == 2:
        # R2-3-1: a settings override may have replaced `default_branch` with a SCALAR (e.g.
        # {settings: {default_branch: "develop"}}) — it passes the bare-list/unknown-key/floor guards
        # but `dict(<scalar>)` would raise a raw ValueError here that escapes the fleet-scan guard.
        # Fail loud with a CompositionError instead (mirrors the other non-dict guards).
        default_branch_settings = settings.get("default_branch", {})
        if not isinstance(default_branch_settings, dict):
            raise CompositionError(
                f"profile {name!r}: settings 'default_branch' must be a mapping, got "
                f"{type(default_branch_settings).__name__} (§4.2/§5.1) — a scalar override is invalid"
            )
        branch = dict(default_branch_settings)
        if profile.workflow_schema == 2:
            branch["required_status_checks"] = status_checks
        else:
            existing = list(branch.get("required_status_checks", ()))
            branch["required_status_checks"] = sorted(set(existing) | set(status_checks))
        settings = {**settings, "default_branch": branch}

    return ResolvedSet(
        profile=name,
        pipelines=pipelines,
        templates=templates,
        settings=settings,
        variables=variables,
        version_source=version_source,
        toolchain=toolchain,
        pipeline_modules=pipeline_modules,
        workflow_schema=profile.workflow_schema,
        scaffold_templates=scaffold_templates,
    )
