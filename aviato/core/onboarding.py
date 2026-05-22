from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
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


def render_variables(variables: Mapping[str, Any], *, pin: str = "main", docs: bool = False) -> dict[str, Any]:
    """Augment the resolved variables with derived render values.

    - ``aviato-ref`` is the declared Library pin (§6.1/§2.6), stamped into the
      generated workflows' ``uses: …@<ref>`` and ``aviato-ref:`` so a consumer runs
      the version it pinned — not ``@main``.
    - ``run-typecheck`` is driven by the ``language-variant`` enum (§12.2).
    - ``docs`` reflects the §6.1 opt-in (gates the docs caller workflow).
    """
    derived = dict(variables)
    derived["aviato-ref"] = pin
    derived["docs"] = "true" if docs else "false"
    derived.setdefault("year", str(date.today().year))
    variant = variables.get("language-variant")
    if variant is not None:
        derived["run-typecheck"] = "false" if variant == "javascript" else "true"
    return derived


def applicable_templates(resolved, variables: Mapping[str, Any]) -> list[TemplateModule]:
    """The resolved templates that apply given the variables (filters §12.2/§6.1 conditionals)."""
    return [t for t in resolved.templates if template_applies(t, variables)]


@dataclass(frozen=True)
class ResolvedArtifact:
    output: str
    body: str  # rendered, without the managed marker
    comment: str
    seed_once: bool


def resolved_artifacts(
    registry: Registry,
    profile: str,
    variables: Mapping[str, Any],
    *,
    pin: str = "main",
    docs: bool = False,
    overrides: Mapping[str, Any] | None = None,
) -> list[ResolvedArtifact]:
    """The fully-resolved, rendered artifact set for a profile (§5.2/§5.3).

    The single source of truth used by onboarding/sync, diagnosis, drift, and the
    fleet scan — so they agree on conditional filtering (§12.2/§6.1) and derived
    render variables (pin, docs, type-check). ``docs`` composes the docs pipeline
    and includes the docs caller workflow.
    """
    resolved = resolve_profile(registry, profile, overrides=dict(overrides or {}), docs=docs)
    render_vars = render_variables(variables, pin=pin, docs=docs)
    artifacts: list[ResolvedArtifact] = []
    for template in applicable_templates(resolved, render_vars):
        body = registry.template_body(template)
        # Seed-once starter files are rendered once (leniently — the developer owns
        # and completes them); managed files are re-rendered strictly every sync.
        rendered = render(body, render_vars, strict=not template.seed_once)
        artifacts.append(ResolvedArtifact(template.output_path, rendered, template.comment or "#", template.seed_once))
    return artifacts


def materialize_items(
    registry: Registry,
    profile: str,
    variables: Mapping[str, Any],
    *,
    pin: str = "main",
    docs: bool = False,
    overrides: Mapping[str, Any] | None = None,
) -> list[ScaffoldItem]:
    """Turn a resolved profile into concrete scaffold items (§5.3).

    ``overrides`` are the consumer's declaration overrides (§4.2); they must be passed
    so the materialized set matches what diagnosis/drift expect for the same repo.
    """
    return [
        ScaffoldItem(output=a.output, body=a.body, comment=a.comment, seed_once=a.seed_once)
        for a in resolved_artifacts(registry, profile, variables, pin=pin, docs=docs, overrides=overrides)
    ]


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
