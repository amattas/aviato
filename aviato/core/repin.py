from __future__ import annotations

from dataclasses import dataclass, field

from .composition import _override_pipeline_list, _unknown_settings_override_paths, resolve_profile
from .declaration import Declaration
from .errors import CompositionError
from .registry import Registry
from .version import _as_lower_bound, normalize_pin

DOWNGRADE_WARNING = (
    "You are moving backward to a lower version; protection or behavior may be "
    "reduced. This change is routed through the normal propose/review path."
)


@dataclass
class RepinPlan:
    target_version: str
    newly_required: list[str] = field(default_factory=list)
    orphaned_overrides: list[str] = field(default_factory=list)
    conflicting_overrides: list[str] = field(default_factory=list)
    downgrade_warning: str | None = None

    @property
    def ok(self) -> bool:
        # R1-8: orphaned overrides are BLOCKING. Composition now hard-rejects unknown settings keys
        # and remove-of-absent pipelines, so a plan that reports orphaned overrides but writes the
        # pin anyway would then fail at the next `aviato sync` (which resolves WITH overrides) — a
        # half-applied move. Refuse until the operator removes the orphaned overrides.
        return not self.newly_required and not self.conflicting_overrides and not self.orphaned_overrides


def _is_downgrade(current: str, target: str) -> bool:
    # review #21: coerce BOTH sides to a comparable lower bound (a floating major `N` floors to
    # `N.0.0`) so a mixed exact→floating move like `1.5.0` → `1` is correctly flagged as backward
    # — the old major-only fallback compared `1 < 1` and silently missed it.
    try:
        return _as_lower_bound(target) < _as_lower_bound(current)
    except Exception:  # noqa: BLE001 - an unparseable pin can't be ranked; don't warn spuriously
        return False


def plan_repin(
    registry: Registry,
    declaration: Declaration,
    target_version: str,
    *,
    target_registry: Registry | None = None,
) -> RepinPlan:
    """Plan moving a Consumer to a different Library version (§5.12).

    Confirms the profile still exists (and resolves) at the target — a profile that
    no longer exists raises :class:`CompositionError`. The declaration's explicit,
    immutable profile identity is compared with the target manifest; a changed identity
    means the name has been **repurposed** and is refused, exactly like "profile no longer
    exists". Evolvable profile composition is deliberately not part of identity. Detects newly-required
    variables (the plan is not ``ok`` until they are supplied) and orphaned overrides
    (settings keys no longer present). A move to a lower version is allowed but carries
    an explicit backward-movement warning. This is the only sanctioned way a pin moves;
    file drift never advances it.

    The binding resolves the requested published ref to one commit and supplies that
    commit's registry as ``target_registry``. The same registry must then drive identity,
    migration planning, and materialization.
    """
    # Canonicalize the target to bare SemVer (§6.1): an operator may type a legacy
    # ``vX.Y.Z`` out of muscle memory, but re-pin is a *write* and must never emit a
    # leading ``v``. An unrecognized pin is refused here rather than persisted.
    target_version = normalize_pin(target_version)

    target_registry = target_registry or registry
    target_identity = target_registry.profile(declaration.profile).identity
    recorded_identity = declaration.profile_identity
    if recorded_identity is None:
        source_identity = registry.profile(declaration.profile).identity
        if source_identity != target_identity:
            raise CompositionError(
                f"legacy profile {declaration.profile!r} changed identity from {source_identity!r} "
                f"to {target_identity!r}; refusing an ambiguous v1-to-v2 re-pin (§5.12/§6.5)"
            )
        recorded_identity = source_identity
    if recorded_identity != target_identity:
        raise CompositionError(
            f"profile {declaration.profile!r} has identity {target_identity!r} at the target version, "
            f"but the declaration records {recorded_identity!r}: it has been repurposed — "
            "refusing to re-pin (§5.12/§6.5). Treat it like a profile change."
        )
    # Resolve the BASE profile at the target (no overrides): variables, settings, and the
    # pipeline set are all override-independent here, and resolving without overrides lets
    # us REPORT orphaned overrides (§5.12) rather than crash on a §4.2 remove-of-absent that
    # an orphaned ``pipelines.remove`` would otherwise raise mid-plan.
    resolved = resolve_profile(target_registry, declaration.profile)

    plan = RepinPlan(target_version=target_version)

    for spec in resolved.variables:
        if spec.required and spec.default is None and spec.name not in declaration.variables:
            plan.newly_required.append(spec.name)

    # R1-3: recurse nested settings-override leaves (not just top-level keys), mirroring the
    # composition unknown-key guard — a nested override like `default_branch.removed_key` that no
    # longer exists at the target is orphaned too (and would now be hard-rejected on re-sync).
    plan.orphaned_overrides.extend(
        _unknown_settings_override_paths(declaration.overrides.get("settings", {}), resolved.settings)
    )

    # A pipeline override that removes a pipeline no longer present at the target is
    # orphaned — report it (don't let merge_list raise remove-of-absent, §5.12/§4.2).
    # N7: the target base profile is resolved WITHOUT overrides, so a malformed `pipelines` override
    # (a bare list, or present-null `add:`/`remove:`) is not validated by composition before reaching
    # here — guard it so it is a clean CompositionError, not a raw AttributeError/TypeError.
    pipeline_override = declaration.overrides.get("pipelines") or {}
    if not isinstance(pipeline_override, dict):
        raise CompositionError("pipelines override must use add/remove, not a bare list (§4.2)")
    # C12-4: validate add/remove are LISTS of non-blank strings (reuse composition's guard) — a bare
    # string `add: common-lint` would otherwise iterate as characters, so plan.ok reads True on a
    # malformed override and `--write` later fails at a more disruptive point (§4.2/§5.12).
    for name in _override_pipeline_list(pipeline_override.get("remove"), "remove"):
        if name not in resolved.pipelines:
            plan.orphaned_overrides.append(name)
    # A pipeline override that ADDS a pipeline the target version now bundles collides
    # (add-of-already-present, §4.2). Surface it at PLAN time and block — otherwise the
    # plan reports ok, the pin is written, and the next `aviato sync` (which resolves WITH
    # overrides) crashes with CompositionError at a far more disruptive point (§5.12).
    for name in _override_pipeline_list(pipeline_override.get("add"), "add"):
        if name in resolved.pipelines:
            plan.conflicting_overrides.append(name)

    if _is_downgrade(declaration.version, target_version):
        plan.downgrade_warning = DOWNGRADE_WARNING

    return plan
