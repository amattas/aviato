from __future__ import annotations

from dataclasses import dataclass, field

from .composition import resolve_profile
from .declaration import Declaration
from .errors import CompositionError
from .registry import Registry
from .version import _pinned_major, parse_version

DOWNGRADE_WARNING = (
    "You are moving backward to a lower version; protection or behavior may be "
    "reduced. This change is routed through the normal propose/review path."
)


@dataclass
class RepinPlan:
    target_version: str
    newly_required: list[str] = field(default_factory=list)
    orphaned_overrides: list[str] = field(default_factory=list)
    downgrade_warning: str | None = None

    @property
    def ok(self) -> bool:
        return not self.newly_required


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
    """
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
    resolved = resolve_profile(target_registry, declaration.profile, overrides=declaration.overrides)

    plan = RepinPlan(target_version=target_version)

    for spec in resolved.variables:
        if spec.required and spec.default is None and spec.name not in declaration.variables:
            plan.newly_required.append(spec.name)

    base_settings = resolve_profile(target_registry, declaration.profile).settings
    for key in declaration.overrides.get("settings", {}):
        if key not in base_settings:
            plan.orphaned_overrides.append(key)

    if _is_downgrade(declaration.version, target_version):
        plan.downgrade_warning = DOWNGRADE_WARNING

    return plan
