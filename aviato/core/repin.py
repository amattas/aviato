from __future__ import annotations

from dataclasses import dataclass, field

from .composition import resolve_profile
from .declaration import Declaration
from .errors import CompositionError
from .registry import Registry
from .version import _pinned_major, normalize_pin, parse_version

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
        return not self.newly_required and not self.conflicting_overrides


def _is_downgrade(current: str, target: str) -> bool:
    try:
        return parse_version(target) < parse_version(current)
    except Exception:  # noqa: BLE001 - fall back to major comparison for floating pins
        try:
            return _pinned_major(target) < _pinned_major(current)
        except Exception:  # noqa: BLE001
            return False


def _profile_identity(registry: Registry, profile: str) -> tuple[str, ...]:
    """A profile's stable identity for re-pin (§6.5): the version-source artifact kind
    it manages. A profile name is a public identity; if the same name maps to a
    different artifact kind at another version it has been repurposed, not evolved."""
    resolved = resolve_profile(registry, profile)
    vs = resolved.version_source
    return tuple(sorted(vs.locations)) if vs is not None else ()


def plan_repin(
    registry: Registry,
    declaration: Declaration,
    target_version: str,
    *,
    target_registry: Registry | None = None,
) -> RepinPlan:
    """Plan moving a Consumer to a different Library version (§5.12).

    Confirms the profile still exists (and resolves) at the target — a profile that
    no longer exists raises :class:`CompositionError`. When a distinct
    ``target_registry`` is given (a genuine cross-version move), the profile's
    identity (its version-source artifact kind, §6.5) is compared between the current
    and target versions; a changed identity means the name has been **repurposed** and
    is refused, exactly like "profile no longer exists". Detects newly-required
    variables (the plan is not ``ok`` until they are supplied) and orphaned overrides
    (settings keys no longer present). A move to a lower version is allowed but carries
    an explicit backward-movement warning. This is the only sanctioned way a pin moves;
    file drift never advances it.

    **Day-zero limitation (§5.12/§6.5):** the §6.5 *repurpose* check (a profile name
    rebound to a different composition at the target version) requires resolving the
    profile **at both versions**, i.e. a distinct ``target_registry``. The operator's
    installed CLI carries exactly **one** Library version, so the shipped ``aviato
    repin`` path passes ``target_registry is registry`` and the identity comparison is
    a structural no-op — it can still confirm the profile *resolves* at the target, but
    cannot detect a cross-version repurpose. Detecting that needs the target version's
    definitions present (a future fetch-the-target-registry step, or running the target
    CLI). The cross-version logic is implemented and exercised by tests that supply a
    second registry; it is dormant in the single-installed-CLI day-zero flow.
    """
    # Canonicalize the target to bare SemVer (§6.1): an operator may type a legacy
    # ``vX.Y.Z`` out of muscle memory, but re-pin is a *write* and must never emit a
    # leading ``v``. An unrecognized pin is refused here rather than persisted.
    target_version = normalize_pin(target_version)

    target_registry = target_registry or registry
    if target_registry is not registry:
        current_identity = _profile_identity(registry, declaration.profile)
        target_identity = _profile_identity(target_registry, declaration.profile)
        if current_identity != target_identity:
            raise CompositionError(
                f"profile {declaration.profile!r} has a different identity at the target version "
                f"(version-source {list(target_identity)} vs {list(current_identity)}): it has been "
                f"repurposed — refusing to re-pin (§5.12/§6.5). Treat it like a profile change."
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

    for key in declaration.overrides.get("settings", {}):
        if key not in resolved.settings:
            plan.orphaned_overrides.append(key)

    # A pipeline override that removes a pipeline no longer present at the target is
    # orphaned — report it (don't let merge_list raise remove-of-absent, §5.12/§4.2).
    pipeline_override = declaration.overrides.get("pipelines", {})
    for name in pipeline_override.get("remove", ()):
        if name not in resolved.pipelines:
            plan.orphaned_overrides.append(name)
    # A pipeline override that ADDS a pipeline the target version now bundles collides
    # (add-of-already-present, §4.2). Surface it at PLAN time and block — otherwise the
    # plan reports ok, the pin is written, and the next `aviato sync` (which resolves WITH
    # overrides) crashes with CompositionError at a far more disruptive point (§5.12).
    for name in pipeline_override.get("add", ()):
        if name in resolved.pipelines:
            plan.conflicting_overrides.append(name)

    if _is_downgrade(declaration.version, target_version):
        plan.downgrade_warning = DOWNGRADE_WARNING

    return plan
