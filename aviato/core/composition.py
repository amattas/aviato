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
        secret=bool(item.get("secret", False)),
        required=bool(item.get("required", True)),
        domain=domain,
        default=item.get("default"),
    )


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
    for layer in layers:
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
    unknown = set(overrides) - {"pipelines", "settings"}
    if unknown:
        raise CompositionError(
            f"unknown override key(s) {sorted(unknown)}; only 'pipelines' and 'settings' "
            f"are supported (§4.2 — overrides are explicit, never silently dropped)"
        )
    profile = registry.profile(name)

    wf_layers: list[WorkflowsBundle] = _chain(registry.workflows_bundle, profile.workflows)
    pipelines = _resolve_list(wf_layers, "pipelines")

    sc_layers: list[ScaffoldBundle] = _chain(registry.scaffold_bundle, profile.scaffold)
    template_refs = _resolve_list(sc_layers, "templates")

    set_layers: list[SettingsBundle] = _chain(registry.settings_bundle, profile.settings)
    settings = _resolve_settings(set_layers)

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
        settings = deep_merge(settings, settings_override)

    templates = tuple(registry.template_module(ref) for ref in template_refs)

    doc = registry.profile_doc(name)

    if docs:
        docs_pipeline = doc.get("docs_pipeline")
        if docs_pipeline and docs_pipeline not in pipelines:
            pipelines = (*pipelines, docs_pipeline)

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
