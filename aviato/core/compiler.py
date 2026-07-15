from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import yaml

from .errors import CompositionError, DeclarationError
from .model import (
    PipelineModule,
    ResolvedSet,
    Unknown,
    UnknownValue,
    WorkflowJobModule,
    deep_freeze,
    deep_thaw,
)
from .onboarding import check_output_collisions, render_variables, template_applies, validate_variable_constraints
from .registry import Registry, validate_actions_job_fragment
from .render import render
from .variables import resolve_declared_variables, resolve_partial_variables

_REFERENCE = {
    "inputs": re.compile(r"\binputs\.([A-Za-z_][\w-]*)\b"),
    "secrets": re.compile(r"\bsecrets\.([A-Za-z_][\w-]*)\b"),
}
_PERMISSION_LEVEL = {"none": 0, "read": 1, "write": 2}
_EXACT_TEMPLATE_VALUE = re.compile(r"^\{\{\s*([A-Za-z_][\w-]*)\s*\}\}$")


class _WorkflowDumper(yaml.SafeDumper):
    """Emit block sequences indented beneath their mapping key for repository policy parity."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, indentless=False)


def _dump_workflow(document: Mapping[str, Any]) -> str:
    return yaml.dump(document, Dumper=_WorkflowDumper, sort_keys=False)


def _render_workflow_node(value: Any, variables: Mapping[str, Any], *, strict: bool) -> Any:
    """Render a workflow AST while retaining native whole-placeholder scalars."""

    if isinstance(value, Mapping):
        return {key: _render_workflow_node(nested, variables, strict=strict) for key, nested in value.items()}
    if isinstance(value, list):
        return [_render_workflow_node(nested, variables, strict=strict) for nested in value]
    if isinstance(value, tuple):
        return [_render_workflow_node(nested, variables, strict=strict) for nested in value]
    if not isinstance(value, str):
        return value
    exact = _EXACT_TEMPLATE_VALUE.fullmatch(value)
    if exact and exact.group(1) in variables:
        selected = variables[exact.group(1)]
        if selected is Unknown or isinstance(selected, UnknownValue):
            if not strict:
                return value
            raise CompositionError(f"undefined variable: {exact.group(1)}")
        return selected
    return render(value, variables, strict=strict)


@dataclass(frozen=True)
class DesiredArtifact:
    output_path: str
    body: str
    seed_once: bool = False
    comment: str = "#"
    owners: tuple[str, ...] = ()
    identity: str = ""
    legacy_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompiledWorkflow:
    envelope: str
    identity: str
    output_path: str
    document: Mapping[str, Any]
    body: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "document", deep_freeze(self.document))


@dataclass(frozen=True)
class DesiredState:
    profile: str
    pipelines: tuple[str, ...]
    artifacts: tuple[DesiredArtifact, ...]
    workflows: tuple[CompiledWorkflow, ...]
    settings: Mapping[str, Any]
    environments: tuple[str, ...]
    required_status_checks: tuple[str, ...]
    privileges: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", deep_freeze(self.settings))


@dataclass(frozen=True)
class PartialDesiredState:
    profile: str
    pipelines: tuple[str, ...]
    definite_artifacts: tuple[str, ...]
    conditional_artifacts: tuple[str, ...]
    definite_settings: tuple[str, ...]
    conditional_settings: tuple[str, ...]
    definite_environments: tuple[str, ...]
    conditional_environments: tuple[str, ...]
    definite_status_checks: tuple[str, ...]
    conditional_status_checks: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    applicable_plan_id: None = None
    applicable: bool = False


def require_workflow_schema_v2(resolved: ResolvedSet, *, operation: str) -> None:
    """Fail closed before a legacy snapshot can drive graph-changing mutation."""

    if resolved.workflow_schema != 2:
        raise CompositionError(
            f"{operation} requires workflow schema v2 for graph mutation; this pinned snapshot is "
            "legacy workflow schema v1. repin to a Library release that declares workflow_schema: 2 "
            "before changing generated automation. Legacy snapshots remain read-only."
        )


def _permission_map(values: tuple[str, ...], *, context: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if ":" not in value:
            raise CompositionError(f"{context} permission {value!r} must use 'scope: level'")
        scope, level = (part.strip() for part in value.split(":", 1))
        if not scope or level not in _PERMISSION_LEVEL:
            raise CompositionError(f"{context} permission {value!r} must use none/read/write")
        prior = result.get(scope)
        if prior is not None and prior != level:
            raise CompositionError(f"{context} has incompatible permissions for {scope!r}")
        result[scope] = level
    return result


def _refs(value: Any, kind: str) -> set[str]:
    return set(_REFERENCE[kind].findall(yaml.safe_dump(value, sort_keys=True)))


def _job_environment(fragment: Mapping[str, Any]) -> str | None:
    value = fragment.get("environment")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str):
            return name
    call_inputs = fragment.get("with")
    if isinstance(call_inputs, Mapping):
        nested = call_inputs.get("environment-name")
        if isinstance(nested, str):
            return nested
    return None


def _validate_job(
    job: WorkflowJobModule,
    fragment: dict[str, Any],
    *,
    workflow_name: str,
    variables: Mapping[str, Any],
) -> None:
    fragment_needs = fragment.get("needs", [])
    if isinstance(fragment_needs, str):
        fragment_needs = [fragment_needs]
    if not isinstance(fragment_needs, list) or any(not isinstance(item, str) for item in fragment_needs):
        raise CompositionError(f"job {job.name!r} fragment needs must be a string or string list")
    if tuple(fragment_needs) != job.needs:
        raise CompositionError(f"job {job.name!r} needs metadata does not match its rendered fragment")

    declared_permissions = _permission_map(job.permissions, context=f"job {job.name!r}")
    fragment_permissions = fragment.get("permissions", {})
    if not isinstance(fragment_permissions, dict) or fragment_permissions != declared_permissions:
        raise CompositionError(f"job {job.name!r} permissions are orphaned or incompatible with its fragment")
    # A reusable-workflow caller has no `runs-on`; its runner is validated
    # against the referenced reusable workflow by repository validation. Local
    # jobs retain exact AST parity here.
    if "uses" not in fragment:
        rendered_runner = fragment.get("runs-on")
        if job.runner != rendered_runner:
            raise CompositionError(f"job {job.name!r} runner metadata does not match its fragment")

    actual_inputs = _refs(fragment, "inputs")
    if job.environment_input:
        actual_inputs.discard(job.environment_input)
    if actual_inputs != set(job.inputs):
        raise CompositionError(
            f"job {job.name!r} inputs are orphaned or undeclared: {sorted(actual_inputs ^ set(job.inputs))}"
        )
    actual_secrets = _refs(fragment, "secrets")
    if actual_secrets != set(job.secrets):
        raise CompositionError(
            f"job {job.name!r} secrets are orphaned or undeclared: {sorted(actual_secrets ^ set(job.secrets))}"
        )

    actual_environment = _job_environment(fragment)
    if job.environment and job.environment_input:
        raise CompositionError(f"job {job.name!r} environment declares both a literal and an input")
    declared_environment = job.environment
    if job.environment_input:
        selected = variables.get(job.environment_input, Unknown)
        # Partial previews deliberately retain an unresolved engine placeholder;
        # validating it as `None` would reject every conditional environment
        # before it can be reported as indeterminate.
        declared_environment = (
            f"{{{{ {job.environment_input} }}}}"
            if selected is Unknown or isinstance(selected, UnknownValue)
            else (None if selected is None else str(selected))
        )
    if actual_environment != declared_environment:
        raise CompositionError(f"job {job.name!r} environment metadata is orphaned or incompatible with its fragment")

    display_name = fragment.get("name", job.name)
    if not isinstance(display_name, str) or not display_name.strip():
        raise CompositionError(f"job {job.name!r} rendered name must be a non-empty string")
    produced_check = f"{workflow_name} / {display_name}"
    if "uses" not in fragment and job.status_check is not None and job.status_check != produced_check:
        raise CompositionError(
            f"job {job.name!r} status check {job.status_check!r} is not produced by the rendered workflow "
            f"(expected {produced_check!r})"
        )


def _list_delta(value: Mapping[str, Any], *, context: str) -> list[Any]:
    unknown = set(value) - {"add", "remove"}
    if unknown:
        raise CompositionError(f"{context} list contribution has unknown key(s) {sorted(unknown)}")
    add = value.get("add", [])
    remove = value.get("remove", [])
    if (
        not isinstance(add, Sequence)
        or isinstance(add, (str, bytes))
        or not isinstance(remove, Sequence)
        or isinstance(remove, (str, bytes))
    ):
        raise CompositionError(f"{context} trigger add/remove values must be lists")
    add = list(add)
    remove = list(remove)
    if len(add) != len(set(map(repr, add))) or len(remove) != len(set(map(repr, remove))):
        raise CompositionError(f"{context} trigger add/remove lists contain duplicates")
    overlap = [item for item in add if item in remove]
    if overlap:
        raise CompositionError(f"{context} trigger contribution both adds and removes {overlap!r}")
    return [item for item in add if item not in remove]


def _is_trigger_delta(value: Any) -> bool:
    return isinstance(value, Mapping) and bool(value) and set(value) <= {"add", "remove"}


def _aggregate_trigger_node(values: list[Any], *, context: str) -> Any:
    deltas = [value for value in values if _is_trigger_delta(value)]
    if deltas:
        if len(deltas) != len(values):
            raise CompositionError(f"incompatible trigger map/list contributions at {context}")
        adds: list[Any] = []
        removes: list[Any] = []
        for delta in deltas:
            _list_delta(delta, context=context)  # validates each contribution independently
            add = list(delta.get("add", []))
            remove = list(delta.get("remove", []))
            adds.extend(add)
            removes.extend(remove)
        add_keys = [repr(item) for item in adds]
        remove_keys = [repr(item) for item in removes]
        if len(add_keys) != len(set(add_keys)):
            raise CompositionError(f"duplicate trigger additions at {context}")
        if len(remove_keys) != len(set(remove_keys)):
            raise CompositionError(f"duplicate trigger removals at {context}")
        add_by_key = {repr(item): item for item in adds}
        orphaned = sorted(set(remove_keys) - set(add_keys))
        if orphaned:
            raise CompositionError(f"orphaned trigger removal at {context}: {orphaned}")
        return [add_by_key[key] for key in sorted(set(add_keys) - set(remove_keys))]

    if all(isinstance(value, Mapping) for value in values):
        result: dict[str, Any] = {}
        raw_keys = {key for value in values for key in value}
        if any(not isinstance(key, str) or not key.strip() for key in raw_keys):
            raise CompositionError(f"trigger contribution at {context} requires non-empty string keys")
        keys = sorted(raw_keys)
        for key in keys:
            present = [value[key] for value in values if key in value]
            result[key] = _aggregate_trigger_node(present, context=f"{context}.{key}")
        return result
    if any(isinstance(value, (Mapping, list, tuple)) for value in values):
        raise CompositionError(f"incompatible or bare-list trigger contribution at {context}")
    first = values[0]
    if any(value != first for value in values[1:]):
        raise CompositionError(f"incompatible trigger contributions at {context}")
    return deepcopy(first)


def _aggregate_triggers(contributions: list[Mapping[str, Any]], *, envelope: str) -> dict[str, Any]:
    if not contributions:
        return {}
    result = _aggregate_trigger_node(list(contributions), context=f"workflow {envelope!r} trigger")
    if not isinstance(result, dict):
        raise CompositionError(f"workflow {envelope!r} trigger must be a mapping")
    return result


def _validate_dag(jobs: Mapping[str, WorkflowJobModule], *, envelope: str) -> None:
    indegree = {name: 0 for name in jobs}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for name, job in jobs.items():
        for dependency in job.needs:
            if dependency not in jobs:
                raise CompositionError(f"job {name!r} in envelope {envelope!r} needs absent job {dependency!r}")
            indegree[name] += 1
            outgoing[dependency].append(name)
    queue = deque(sorted(name for name, degree in indegree.items() if degree == 0))
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for dependent in sorted(outgoing[current]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    if visited != len(jobs):
        raise CompositionError(f"workflow envelope {envelope!r} contains a cyclic needs graph")


def _validate_pipeline_dag(modules: Mapping[str, PipelineModule]) -> None:
    indegree = {name: 0 for name in modules}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for name, module in modules.items():
        for dependency in module.required_pipelines:
            indegree[name] += 1
            outgoing[dependency].append(name)
    queue = deque(sorted(name for name, degree in indegree.items() if degree == 0))
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for dependent in sorted(outgoing[current]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    if visited != len(modules):
        raise CompositionError("selected pipelines contain a cyclic required-pipeline graph")


def _validate_pipeline_aggregates(module: PipelineModule) -> None:
    job_privileges: dict[str, str] = {}
    for job in module.jobs:
        for scope, level in _permission_map(job.permissions, context=f"job {job.name!r}").items():
            prior = job_privileges.get(scope, "none")
            if _PERMISSION_LEVEL[level] > _PERMISSION_LEVEL[prior]:
                job_privileges[scope] = level
    if "privileges" in module.declared_aggregates:
        aggregate_privileges = _permission_map(module.privileges, context=f"pipeline {module.name!r}")
        if aggregate_privileges != job_privileges:
            raise CompositionError(
                f"pipeline {module.name!r} aggregate permissions metadata does not equal its job graph"
            )

    exact_sets = {
        "inputs": (set(module.inputs), {item for job in module.jobs for item in job.inputs}),
        "secrets": (set(module.secrets), {item for job in module.jobs for item in job.secrets}),
    }
    for field, (aggregate_set, derived_set) in exact_sets.items():
        if field in module.declared_aggregates and aggregate_set != derived_set:
            raise CompositionError(f"pipeline {module.name!r} aggregate {field} metadata does not equal its job graph")

    exact_scalars = {
        "runner": (module.runner, {job.runner for job in module.jobs if job.runner}),
        "status_check": (module.status_check, {job.status_check for job in module.jobs if job.status_check}),
        "environment": (module.environment, {job.environment for job in module.jobs if job.environment}),
        "environment_input": (
            module.environment_input,
            {job.environment_input for job in module.jobs if job.environment_input},
        ),
    }
    for field, (aggregate_scalar, derived_values) in exact_scalars.items():
        if field not in module.declared_aggregates:
            continue
        if len(derived_values) > 1:
            raise CompositionError(
                f"pipeline {module.name!r} provided aggregate {field.replace('_', ' ')} cannot represent "
                f"multiple job values {sorted(derived_values)}"
            )
        derived_scalar = next(iter(derived_values), None)
        if aggregate_scalar != derived_scalar:
            raise CompositionError(
                f"pipeline {module.name!r} aggregate {field.replace('_', ' ')} metadata does not equal its job graph"
            )


def _setting_paths(value: Mapping[str, Any], prefix: str = "") -> tuple[str, ...]:
    paths: list[str] = []
    for key in sorted(value):
        path = f"{prefix}.{key}" if prefix else key
        nested = value[key]
        if isinstance(nested, Mapping):
            paths.extend(_setting_paths(nested, path))
        else:
            paths.append(path)
    return tuple(paths)


def _render_template_artifacts(
    registry: Registry,
    resolved: ResolvedSet,
    variables: Mapping[str, Any],
    *,
    pin: str,
    partial: bool,
    docs: bool,
    bootstrap: bool,
) -> tuple[list[DesiredArtifact], list[str], list[str]]:
    derived = render_variables(
        {key: value for key, value in variables.items() if value is not Unknown and value is not None},
        pin=pin,
        docs=docs,
        bootstrap=bootstrap,
        library_repository=registry.library_repository(),
        derived_rules=registry.profile_doc(resolved.profile).get("derived_variables", []),
    )
    # Conditions must see Unknown values even though rendering must never stringify them.
    conditions = {**variables, **derived}
    applicable = []
    conditional: list[str] = []
    for template in resolved.templates:
        state = template_applies(template, conditions)
        if state is True:
            applicable.append(template)
        elif state is Unknown:
            conditional.append(template.output_path)
    check_output_collisions(applicable)
    base_outputs = {template.output_path for template in resolved.scaffold_templates}
    pipeline_owners: dict[str, set[str]] = defaultdict(set)
    for module in resolved.pipeline_modules:
        if module.identity is None:
            continue
        for template_ref in module.artifacts:
            pipeline_owners[registry.template_module(template_ref).output_path].add(module.identity)
    artifacts: list[DesiredArtifact] = []
    for template in sorted(applicable, key=lambda item: item.output_path):
        body = registry.template_body(template)
        rendered = render(body, derived, strict=not template.seed_once and not partial)
        owners = set(pipeline_owners.get(template.output_path, set()))
        if template.output_path in base_outputs:
            owners.add("scaffold")
        artifacts.append(
            DesiredArtifact(
                template.output_path,
                rendered,
                template.seed_once,
                template.comment or "#",
                tuple(sorted(owners)),
                template.identity,
                template.legacy_aliases,
            )
        )
    return artifacts, sorted({item.output_path for item in applicable}), sorted(set(conditional))


def _compile_workflows(
    registry: Registry,
    resolved: ResolvedSet,
    variables: Mapping[str, Any],
    *,
    pin: str,
    partial: bool,
    docs: bool,
    bootstrap: bool,
) -> tuple[list[CompiledWorkflow], set[str], set[str], set[str]]:
    selected = set(resolved.pipelines)
    modules = {module.name: module for module in resolved.pipeline_modules}
    missing_modules = sorted(selected - set(modules))
    if missing_modules:
        raise CompositionError(f"workflow schema v2 pipeline(s) lack graph modules: {missing_modules}")
    pipeline_ids: dict[str, str] = {}
    global_job_ids: dict[str, str] = {}
    global_job_identities: dict[str, str] = {}
    check_producers: dict[str, str] = {}
    for module in modules.values():
        if not module.identity or not module.envelope or not module.jobs:
            raise CompositionError(f"pipeline {module.name!r} is incomplete for workflow schema v2")
        if module.identity in pipeline_ids:
            raise CompositionError(
                f"duplicate pipeline identity {module.identity!r}: "
                f"{pipeline_ids[module.identity]!r} and {module.name!r}"
            )
        pipeline_ids[module.identity] = module.name
        missing_dependencies = sorted(set(module.required_pipelines) - selected)
        if missing_dependencies:
            raise CompositionError(
                f"pipeline {module.name!r} is missing required pipeline dependency(ies) {missing_dependencies}"
            )
        if module.triggers and not module.jobs:
            raise CompositionError(f"pipeline {module.name!r} contributes orphaned triggers without jobs")
        for job in module.jobs:
            if job.name in global_job_ids:
                raise CompositionError(
                    f"duplicate job ID {job.name!r} in pipelines {global_job_ids[job.name]!r} and {module.name!r}"
                )
            global_job_ids[job.name] = module.name
            if job.identity in global_job_identities:
                raise CompositionError(
                    f"duplicate job identity {job.identity!r} in pipelines "
                    f"{global_job_identities[job.identity]!r} and {module.name!r}"
                )
            global_job_identities[job.identity] = module.name
            if job.status_check:
                if job.status_check in check_producers:
                    raise CompositionError(
                        f"duplicate status check producer {job.status_check!r}: "
                        f"{check_producers[job.status_check]!r} and {job.identity!r}"
                    )
                check_producers[job.status_check] = job.identity

        _validate_pipeline_aggregates(module)

    _validate_pipeline_dag(modules)

    by_envelope: dict[str, list[PipelineModule]] = defaultdict(list)
    for name in resolved.pipelines:
        by_envelope[modules[name].envelope or ""].append(modules[name])

    workflows: list[CompiledWorkflow] = []
    checks: set[str] = set()
    environments: set[str] = set()
    privilege_union: dict[str, str] = {}
    output_paths: set[str] = set()
    render_vars = render_variables(
        {key: value for key, value in variables.items() if value is not Unknown and value is not None},
        pin=pin,
        docs=docs,
        bootstrap=bootstrap,
        library_repository=registry.library_repository(),
        derived_rules=registry.profile_doc(resolved.profile).get("derived_variables", []),
    )
    # These values are booleans in Actions reusable-workflow contracts. Legacy
    # text templates used lowercase strings; graph AST rendering keeps them typed.
    render_vars["aviato-local-install"] = bootstrap
    render_vars["docs"] = docs
    profile_parameters = registry.profile_doc(resolved.profile).get("workflow_parameters", {})
    if not isinstance(profile_parameters, Mapping) or any(
        not isinstance(key, str) or not key.strip() for key in profile_parameters
    ):
        raise CompositionError(f"profile {resolved.profile!r} workflow_parameters must be a string-keyed mapping")
    overlap = sorted(set(render_vars) & set(profile_parameters))
    if overlap:
        raise CompositionError(
            f"profile {resolved.profile!r} workflow_parameters collide with rendered variables {overlap}"
        )
    rendered_parameters: dict[str, Any] = {}
    for key, value in profile_parameters.items():
        if not isinstance(value, (str, bool, int, float)) and value is not None:
            raise CompositionError(f"profile {resolved.profile!r} workflow parameter {key!r} must be a scalar")
        rendered_value = _render_workflow_node(value, render_vars, strict=not partial)
        if not isinstance(rendered_value, (str, bool, int, float)) and rendered_value is not None:
            raise CompositionError(
                f"profile {resolved.profile!r} rendered workflow parameter {key!r} must remain a scalar"
            )
        rendered_parameters[key] = rendered_value
    render_vars = {**render_vars, **rendered_parameters}
    for envelope_name in sorted(by_envelope):
        envelope = registry.workflow_envelope(envelope_name)
        if envelope.output_path in output_paths:
            raise CompositionError(f"duplicate workflow output path {envelope.output_path!r}")
        output_paths.add(envelope.output_path)
        jobs: dict[str, WorkflowJobModule] = {}
        fragments: dict[str, dict[str, Any]] = {}
        raw_triggers = _aggregate_triggers(
            [module.triggers for module in by_envelope[envelope_name]], envelope=envelope_name
        )
        triggers = _render_workflow_node(deep_thaw(raw_triggers), render_vars, strict=not partial)
        if not isinstance(triggers, dict):
            raise CompositionError(f"workflow envelope {envelope_name!r} rendered triggers must be a mapping")
        workflow_name = render(envelope.display_name, render_vars, strict=not partial)
        job_permission_union: dict[str, str] = {}
        for module in by_envelope[envelope_name]:
            for job in module.jobs:
                if job.name in jobs:
                    raise CompositionError(f"duplicate job ID {job.name!r} in workflow envelope {envelope_name!r}")
                jobs[job.name] = job
                fragment = registry.workflow_fragment(job.fragment)
                loaded = _render_workflow_node(fragment, render_vars, strict=not partial)
                loaded = validate_actions_job_fragment(
                    loaded,
                    context=f"rendered job {job.name!r} in workflow {workflow_name!r}",
                )
                _validate_job(job, loaded, workflow_name=workflow_name, variables=variables)
                fragments[job.name] = loaded
                for scope, level in _permission_map(job.permissions, context=f"job {job.name!r}").items():
                    prior = job_permission_union.get(scope, "none")
                    if _PERMISSION_LEVEL[level] > _PERMISSION_LEVEL[prior]:
                        job_permission_union[scope] = level
                    global_prior = privilege_union.get(scope, "none")
                    if _PERMISSION_LEVEL[level] > _PERMISSION_LEVEL[global_prior]:
                        privilege_union[scope] = level
                if job.status_check:
                    checks.add(job.status_check)
                if job.environment:
                    environments.add(job.environment)
                elif job.environment_input:
                    value = variables.get(job.environment_input, Unknown)
                    if value is not Unknown and value is not None and str(value).strip():
                        environments.add(str(value))
        _validate_dag(jobs, envelope=envelope_name)
        if not triggers:
            raise CompositionError(f"workflow envelope {envelope_name!r} has jobs but no trigger contribution")
        for scope, level in envelope.permissions:
            if _PERMISSION_LEVEL[level] > _PERMISSION_LEVEL[job_permission_union.get(scope, "none")]:
                raise CompositionError(
                    f"workflow {envelope_name!r} privilege {scope}: {level} is broader than the selected job graph"
                )
        document: dict[str, Any] = {"name": workflow_name, "on": triggers}
        document["permissions"] = dict(envelope.permissions)
        if envelope.concurrency:
            document["concurrency"] = dict(envelope.concurrency)
        document["jobs"] = {name: fragments[name] for name in sorted(fragments)}
        body = _dump_workflow(document)
        workflows.append(
            CompiledWorkflow(
                envelope=envelope_name,
                identity=envelope.identity,
                output_path=envelope.output_path,
                document=document,
                body=body,
            )
        )
    privileges = {f"{scope}: {level}" for scope, level in privilege_union.items()}
    return workflows, checks, environments, privileges


def compile_desired_state(
    registry: Registry,
    resolved: ResolvedSet,
    variables: Mapping[str, Any],
    *,
    pin: str,
    docs: bool = False,
    bootstrap: bool = False,
) -> DesiredState:
    """Compile one exact, deterministic, mutation-capable desired state."""

    require_workflow_schema_v2(resolved, operation="desired-state compilation")
    registry.validate_workflow_graph_manifest()
    if any(value is Unknown or isinstance(value, UnknownValue) for value in variables.values()):
        raise CompositionError("exact desired state requires complete typed variables")
    try:
        exact = resolve_declared_variables(resolved.variables, variables)
        validate_variable_constraints(registry, resolved.profile, exact)
    except DeclarationError as exc:
        raise CompositionError(f"exact desired state requires complete typed variables: {exc}") from exc
    artifacts, _, _ = _render_template_artifacts(
        registry, resolved, exact, pin=pin, partial=False, docs=docs, bootstrap=bootstrap
    )
    workflows, checks, environments, privileges = _compile_workflows(
        registry, resolved, exact, pin=pin, partial=False, docs=docs, bootstrap=bootstrap
    )
    seen_paths = {artifact.output_path for artifact in artifacts}
    for workflow in workflows:
        if workflow.output_path in seen_paths:
            raise CompositionError(f"duplicate artifact path {workflow.output_path!r}")
        seen_paths.add(workflow.output_path)
        workflow_owners = {workflow.identity}
        workflow_owners.update(
            module.identity
            for module in resolved.pipeline_modules
            if module.envelope == workflow.envelope and module.identity is not None
        )
        artifacts.append(
            DesiredArtifact(
                workflow.output_path,
                workflow.body,
                False,
                "#",
                tuple(sorted(workflow_owners)),
                workflow.identity,
            )
        )
    settings = deep_thaw(resolved.settings)
    branch = settings.setdefault("default_branch", {})
    if not isinstance(branch, dict):
        raise CompositionError("desired default_branch settings must be a mapping")
    branch["required_status_checks"] = sorted(checks)
    return DesiredState(
        profile=resolved.profile,
        pipelines=tuple(resolved.pipelines),
        artifacts=tuple(sorted(artifacts, key=lambda item: item.output_path)),
        workflows=tuple(sorted(workflows, key=lambda item: item.output_path)),
        settings=settings,
        environments=tuple(sorted(environments)),
        required_status_checks=tuple(sorted(checks)),
        privileges=tuple(sorted(privileges)),
    )


def compile_partial_desired_state(
    registry: Registry,
    resolved: ResolvedSet,
    variables: Mapping[str, Any],
    *,
    pin: str,
    docs: bool = False,
    bootstrap: bool = False,
) -> PartialDesiredState:
    """Compile a non-applicable read-only preview that preserves unknowns."""

    require_workflow_schema_v2(resolved, operation="partial desired-state preview")
    registry.validate_workflow_graph_manifest()
    known_names = {spec.name for spec in resolved.variables}
    unknown_names = sorted(set(variables) - known_names)
    if unknown_names:
        raise CompositionError(f"partial desired state has unknown variable key(s): {unknown_names}")
    supplied = {name: value for name, value in variables.items() if value is not Unknown}
    try:
        partial_variables = resolve_partial_variables(
            resolved.variables,
            flags=supplied,
            declaration={},
            env={},
            autodetect={},
        )
    except DeclarationError as exc:
        raise CompositionError(f"partial desired state has invalid typed variables: {exc}") from exc
    partial_values = partial_variables.values
    missing = tuple(sorted(partial_variables.missing))
    artifacts, definite, conditional = _render_template_artifacts(
        registry, resolved, partial_values, pin=pin, partial=True, docs=docs, bootstrap=bootstrap
    )
    del artifacts
    workflows, checks, environments, _ = _compile_workflows(
        registry, resolved, partial_values, pin=pin, partial=True, docs=docs, bootstrap=bootstrap
    )
    definite.extend(workflow.output_path for workflow in workflows)
    conditional_environments = sorted(
        {
            job.environment_input
            for module in resolved.pipeline_modules
            for job in module.jobs
            if job.environment_input and partial_values.get(job.environment_input, Unknown) is Unknown
        }
    )
    return PartialDesiredState(
        profile=resolved.profile,
        pipelines=tuple(resolved.pipelines),
        definite_artifacts=tuple(sorted(set(definite))),
        conditional_artifacts=tuple(sorted(set(conditional))),
        definite_settings=_setting_paths(resolved.settings),
        conditional_settings=(),
        definite_environments=tuple(sorted(environments)),
        conditional_environments=tuple(conditional_environments),
        definite_status_checks=tuple(sorted(checks)),
        conditional_status_checks=(),
        missing_inputs=missing,
    )
