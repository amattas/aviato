from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .composition import resolve_profile
from .declaration import Declaration
from .errors import CompositionError, DeclarationError
from .model import TemplateModule
from .registry import Registry
from .render import render
from .scaffold import ScaffoldItem


def _canon(value: Any) -> str:
    """Canonical string for a ``when`` comparison (R1-2/§12.2).

    Booleans canonicalize to ``"true"``/``"false"`` regardless of source shape, so an UNQUOTED
    `when: {docs: true}` (YAML bool `True` → `"True"`) still matches the derived `"true"` instead of
    silently excluding the template. Non-booleans compare by their plain string form.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    return text.lower() if text.lower() in ("true", "false") else text


def template_applies(template: TemplateModule, variables: Mapping[str, Any]) -> bool:
    """True if a conditional template's ``when`` matches the resolved variables (§12.2)."""
    return all(_canon(variables.get(key)) == _canon(value) for key, value in template.when)


def render_variables(
    variables: Mapping[str, Any],
    *,
    pin: str,
    docs: bool = False,
    bootstrap: bool = False,
    derived_rules: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Augment the resolved variables with derived render values.

    - ``aviato-ref`` is the declared Library pin (§6.1/§2.6), stamped into the
      generated workflows' ``uses: …@<ref>`` and ``aviato-ref:`` so a consumer runs
      the version it pinned — not ``@main``.
    - ``docs`` reflects the §6.1 opt-in (gates the docs caller workflow).
    - ``derived_rules`` are plug-in DATA from the profile (``derived_variables``):
      each maps another variable's value onto a derived render variable. Applying
      them generically keeps language-specific knowledge (e.g. which variant skips
      type-checking) out of the agnostic core (§9b).
    """
    derived = dict(variables)
    derived["aviato-ref"] = pin
    if bootstrap:
        derived["aviato-workflow-prefix"] = "./.github/workflows/"
        derived["aviato-workflow-suffix"] = ""
        derived["aviato-local-install"] = "true"
    else:
        derived["aviato-workflow-prefix"] = "amattas/aviato/.github/workflows/"
        derived["aviato-workflow-suffix"] = f"@{pin}"
        derived["aviato-local-install"] = "false"
    derived["docs"] = "true" if docs else "false"
    derived.setdefault("year", str(date.today().year))
    # R4-3: the default branch is templated into the generated callers' trigger filters and
    # release-gate input (GitHub Actions trigger `branches:` cannot use `${{ }}` expressions, so
    # it must be a render-time literal). A consumer whose default branch isn't `main` overrides it
    # via the `default-branch` profile variable; absent that (and for the direct-render paths used
    # by diagnosis/parity that don't go through variable resolution) it defaults to `main`.
    derived.setdefault("default-branch", "main")
    for rule in derived_rules:
        # R2-3-3: a malformed rule missing `from`/`name` must fail loud as a CompositionError, not a
        # raw KeyError that escapes the fleet-scan guard (R1-1). `derived_variables` is Library data.
        if not isinstance(rule, Mapping) or "from" not in rule or "name" not in rule:
            raise CompositionError(f"derived_variables rule must declare 'from' and 'name': {rule!r} (§9b)")
        source_value = variables.get(rule["from"])
        if source_value is not None:
            mapped = rule.get("cases", {}).get(source_value, rule.get("default"))
            # R2-3-3: only set the derived var when it resolves to a real value. A rule whose source
            # value isn't in `cases` and declares NO `default` resolves to None; setting it would bake
            # the literal string "None" into the workflow (a DEFINED key, so strict render's undefined
            # guard wouldn't fire). Leaving it unset instead surfaces a clear "undefined variable" error.
            if mapped is not None:
                derived[rule["name"]] = mapped
    return derived


def validate_variable_constraints(registry: Registry, profile: str, variables: Mapping[str, Any]) -> None:
    """Apply profile-declared cross-variable constraints before rendering (§12.3)."""
    constraints = registry.profile_doc(profile).get("variable_constraints", {})
    for names in constraints.get("any_of", []):
        if not any(str(variables.get(name) or "").strip() for name in names):
            joined = ", ".join(repr(name) for name in names)
            raise DeclarationError(f"profile {profile!r} requires at least one of {joined} to be set (§12.3)")


def applicable_templates(resolved, variables: Mapping[str, Any]) -> list[TemplateModule]:
    """The resolved templates that apply given the variables (filters §12.2/§6.1 conditionals)."""
    return [t for t in resolved.templates if template_applies(t, variables)]


def check_output_collisions(templates: Iterable[TemplateModule]) -> None:
    """Fail on two templates writing the same output path (§4.2 tie = error, not silent pick).

    Called on the *applicable* set (post ``when`` filtering), so variant-exclusive
    templates that share a path (e.g. mutually-exclusive language-variant manifest
    templates) are fine — only one is ever applicable. Two applicable templates at one
    path is a real collision the resolution must not silently resolve.
    """
    seen: set[str] = set()
    for template in templates:
        if template.output_path in seen:
            raise CompositionError(
                f"two applicable templates write {template.output_path!r}; "
                f"a same-path collision is a hard error, not a silent pick (§4.2)"
            )
        seen.add(template.output_path)


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
    pin: str,
    docs: bool = False,
    bootstrap: bool = False,
    overrides: Mapping[str, Any] | None = None,
) -> list[ResolvedArtifact]:
    """The fully-resolved, rendered artifact set for a profile (§5.2/§5.3).

    The single source of truth used by onboarding/sync, diagnosis, drift, and the
    fleet scan — so they agree on conditional filtering (§12.2/§6.1) and derived
    render variables (pin, docs, type-check). ``docs`` composes the docs pipeline
    and includes the docs caller workflow.
    """
    resolved = resolve_profile(registry, profile, overrides=dict(overrides or {}), docs=docs)
    derived_rules = registry.profile_doc(profile).get("derived_variables", [])
    effective_variables = {spec.name: spec.default for spec in resolved.variables if spec.default is not None}
    effective_variables.update(variables)
    validate_variable_constraints(registry, profile, effective_variables)
    # finding 28: resolve_variables emits None for unset OPTIONAL variables; render()
    # substitutes str(value) for any present key, so a None entry would bake the
    # literal "None" into bodies (the derived-rules path below documents the same
    # hazard). Omit None entries: lenient seed-once renders then PRESERVE the
    # {{ placeholder }} for the operator, and strict renders fail loud.
    # finding 11 (§8.15 render-side analogue of writeback_variables): secret-typed
    # values must never reach a rendered body — managed bodies are committed and
    # seed-once bodies persist in the consumer tree. With the name dropped, a
    # template referencing it fails strict render (managed) or keeps the
    # placeholder (seed-once) instead of leaking the value.
    secret_names = {spec.name for spec in resolved.variables if spec.secret}
    effective_variables = {
        name: value for name, value in effective_variables.items() if value is not None and name not in secret_names
    }
    render_vars = render_variables(
        effective_variables, pin=pin, docs=docs, bootstrap=bootstrap, derived_rules=derived_rules
    )
    applicable = applicable_templates(resolved, render_vars)
    check_output_collisions(applicable)
    artifacts: list[ResolvedArtifact] = []
    for template in applicable:
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
    pin: str,
    docs: bool = False,
    bootstrap: bool = False,
    overrides: Mapping[str, Any] | None = None,
) -> list[ScaffoldItem]:
    """Turn a resolved profile into concrete scaffold items (§5.3).

    ``overrides`` are the consumer's declaration overrides (§4.2); they must be passed
    so the materialized set matches what diagnosis/drift expect for the same repo.
    """
    return [
        ScaffoldItem(output=a.output, body=a.body, comment=a.comment, seed_once=a.seed_once)
        for a in resolved_artifacts(
            registry, profile, variables, pin=pin, docs=docs, bootstrap=bootstrap, overrides=overrides
        )
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

    # R1-10: pass an explicit placeholder pin — the plan only consumes output PATHS (not the
    # rendered `@ref` content), so the pin value is immaterial here, but we pass it explicitly
    # rather than rely on a silent default that could stamp an unpinned `@main` ref elsewhere.
    items = materialize_items(registry, profile, variables, pin="0")
    plan = OnboardingPlan(profile=profile, migrating_from=migrating_from)
    for item in items:
        if item.seed_once:
            plan.seed_once_outputs.append(item.output)
        else:
            plan.outputs.append(item.output)
    return plan
