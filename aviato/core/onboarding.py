from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .composition import resolve_profile
from .declaration import Declaration
from .errors import DeclarationError
from .model import TemplateModule
from .registry import Registry
from .render import render
from .scaffold import ScaffoldItem


def template_applies(template: TemplateModule, variables: Mapping[str, Any]) -> bool:
    """True if a conditional template's ``when`` matches the resolved variables (§12.2)."""
    return all(str(variables.get(key)) == value for key, value in template.when)


def render_variables(variables: Mapping[str, Any]) -> dict[str, Any]:
    """Augment the resolved variables with derived render values.

    ``run-typecheck`` is driven by the ``language-variant`` enum (§12.2): TypeScript
    type-checks, JavaScript does not. This is what selects JS vs TS behavior — not
    tsconfig.json presence.
    """
    derived = dict(variables)
    variant = variables.get("language-variant")
    if variant is not None:
        derived["run-typecheck"] = "false" if variant == "javascript" else "true"
    return derived


def applicable_templates(resolved, variables: Mapping[str, Any]) -> list[TemplateModule]:
    """The resolved templates that apply given the variables (filters §12.2 conditionals)."""
    return [t for t in resolved.templates if template_applies(t, variables)]


def materialize_items(registry: Registry, profile: str, variables: Mapping[str, Any]) -> list[ScaffoldItem]:
    """Turn a resolved profile into concrete scaffold items (§5.3).

    Conditional templates that do not apply to the variables are skipped (§12.2).
    Managed bodies are rendered with the resolved + derived variables; seed-once
    bodies are written verbatim. Feeds :func:`aviato.core.scaffold.scaffold`.
    """
    resolved = resolve_profile(registry, profile)
    render_vars = render_variables(variables)
    items: list[ScaffoldItem] = []
    for template in applicable_templates(resolved, variables):
        body = registry.template_body(template)
        rendered = body if template.seed_once else render(body, render_vars)
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
