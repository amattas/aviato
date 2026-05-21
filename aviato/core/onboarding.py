from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .composition import resolve_profile
from .declaration import Declaration
from .errors import DeclarationError
from .registry import Registry
from .render import render
from .scaffold import ScaffoldItem


def materialize_items(registry: Registry, profile: str, variables: Mapping[str, Any]) -> list[ScaffoldItem]:
    """Turn a resolved profile into concrete scaffold items (§5.3).

    Managed bodies are rendered with the resolved variables; seed-once bodies are
    written verbatim (their placeholders, if any, are filled at seed time by the
    operator who owns them). The result feeds :func:`aviato.core.scaffold.scaffold`.
    """
    resolved = resolve_profile(registry, profile)
    items: list[ScaffoldItem] = []
    for template in resolved.templates:
        body = registry.template_body(template)
        rendered = body if template.seed_once else render(body, variables)
        items.append(
            ScaffoldItem(
                output=template.output_path,
                body=rendered,
                comment=template.comment or "#",
                seed_once=template.seed_once,
            )
        )
    return items


@dataclass
class OnboardingPlan:
    profile: str
    outputs: list[str] = field(default_factory=list)
    seed_once_outputs: list[str] = field(default_factory=list)
    migrating_from: str | None = None


def plan_onboarding(
    registry: Registry,
    *,
    profile: str,
    existing_declaration: Declaration | None,
    variables: Mapping[str, Any],
    allow_migrate: bool = False,
) -> OnboardingPlan:
    """Plan onboarding a repository to ``profile`` (§5.2).

    Refuses to change an already-declared profile to a different one without an
    explicit migrate override. Returns the set of managed and seed-once outputs
    that would be materialized.
    """
    migrating_from: str | None = None
    if existing_declaration is not None and existing_declaration.profile != profile:
        if not allow_migrate:
            raise DeclarationError(
                f"repository already declares profile {existing_declaration.profile!r}; "
                f"pass allow_migrate to change it to {profile!r}"
            )
        migrating_from = existing_declaration.profile

    items = materialize_items(registry, profile, variables)
    plan = OnboardingPlan(profile=profile, migrating_from=migrating_from)
    for item in items:
        if item.seed_once:
            plan.seed_once_outputs.append(item.output)
        else:
            plan.outputs.append(item.output)
    return plan
