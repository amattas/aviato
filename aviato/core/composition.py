from __future__ import annotations

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
    override: dict[str, Any], baseline: dict[str, Any], _prefix: str = ""
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
        elif isinstance(value, dict) and isinstance(baseline.get(key), dict):
            unknown.extend(_unknown_settings_override_paths(value, baseline[key], f"{path}."))
    return unknown


def _chain(load, name: str) -> list:
    """Walk an ``extends`` chain from ``name`` to its root, root-first.

    ``load`` maps a bundle name to its dataclass. Ancestors resolve before
    descendants (§4.2 deterministic ordering).
    """
    layers: list = []
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


def _resolve_list(layers: list, base_attr: str) -> tuple[str, ...]:
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
            bare = _settings_override_lists(layer.settings)
            if bare:
                raise CompositionError(
                    f"settings bundle {layer.name!r} restates list-valued key(s) {sorted(bare)} "
                    f"under extends; settings lists are base-only and cannot be replaced by a child "
                    f"bundle (§4.2)"
                )
        resolved = deep_merge(resolved, layer.settings)
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

    pipeline_override = overrides.get("pipelines")
    if pipeline_override is not None:
        if not isinstance(pipeline_override, dict):
            raise CompositionError("pipelines override must use add/remove, not a bare list (§4.2)")
        pipelines = tuple(
            merge_list(
                list(pipelines),
                add=pipeline_override.get("add", ()),
                remove=pipeline_override.get("remove", ()),
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

    templates = tuple(registry.template_module(ref) for ref in template_refs)

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
        unknown = sorted(ref for ref in pipelines if ref not in declared)
        if unknown:
            raise CompositionError(
                f"profile {name!r} references undeclared pipeline(s) {unknown}; every pipeline must be "
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
    vs_doc = doc.get("version_source")
    version_source = VersionSourceModule(locations=tuple(vs_doc.get("locations", ()))) if vs_doc is not None else None
    # CX#2/§12.3: a consumer may OVERRIDE version_source.locations in its declaration — the
    # documented path when a profile's day-zero placeholder locations do not match the project's
    # actual layout. `locations` is config data (WHERE the version is written), not a composed
    # module list, so the override REPLACES it (an explicit operator choice, §4.2) rather than
    # using add/remove. Only valid when the profile actually declares a version_source. (No
    # language/target identifier appears here — the example path is generic — to keep core agnostic.)
    vs_override = overrides.get("version_source")
    if vs_override is not None:
        if not isinstance(vs_override, dict) or not isinstance(vs_override.get("locations"), list):
            raise CompositionError(
                "version_source override must be a mapping with a 'locations' list (§12.3) — "
                "e.g. version_source: {locations: ['path/to/your/version-file']}"
            )
        if version_source is None:
            raise CompositionError(f"profile {name!r} declares no version_source, so it cannot be overridden (§12.3)")
        # R5-10: a `locations` list that is empty, or carries a non-string / blank entry, parses but
        # silently disables the version-source (or feeds a bogus path) downstream in version tooling
        # (§12.1). Reject it here, fail-closed, so the operator fixes the override rather than getting
        # a no-op bump. (`bool` is an int subclass but not a str, so it is correctly rejected.)
        locations = vs_override["locations"]
        if not locations or any(not isinstance(loc, str) or not loc.strip() for loc in locations):
            raise CompositionError(
                "version_source override 'locations' must be a non-empty list of non-blank path "
                "strings (§12.3) — e.g. version_source: {locations: ['path/to/your/version-file']}"
            )
        version_source = VersionSourceModule(locations=tuple(locations))
    toolchain = dict(doc.get("toolchain", {}))

    # Resolve each pipeline reference to its typed module (privileges/inputs/
    # secrets/runner, §3.2/§11.3). Undeclared pipelines (e.g. in a test registry)
    # are simply absent from pipeline_modules.
    pipeline_modules = tuple(module for ref in pipelines if (module := registry.pipeline_module(ref)) is not None)

    # §10/#5: the merge gate must require exactly the checks the profile's composed
    # pipelines produce. Union the per-pipeline status_check contexts (e.g. the
    # language verify job) into the desired branch protection — single source of
    # truth, so a profile cannot require a check it never runs (or omit one it does).
    status_checks = sorted({m.status_check for m in pipeline_modules if m.status_check})
    if status_checks:
        branch = dict(settings.get("default_branch", {}))
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
    )
