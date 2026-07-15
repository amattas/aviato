from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ..policy import library_repository, load_policy
from .errors import CompositionError
from .model import (
    PipelineModule,
    Profile,
    ScaffoldBundle,
    SettingsBundle,
    TemplateModule,
    WorkflowEnvelopeModule,
    WorkflowJobModule,
    WorkflowsBundle,
)
from .pathguard import confined_target


def _validate_mapping_keys(value: object, context: str) -> None:
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_mapping_keys(nested, f"{context}[{index}]")
        return
    if not isinstance(value, dict):
        return
    for key, nested in value.items():
        if not isinstance(key, str) or not key.strip():
            raise CompositionError(f"{context} mapping requires non-empty string keys")
        _validate_mapping_keys(nested, f"{context}.{key}")


def _load_doc(root: Path, relative: str) -> dict[str, Any]:
    path = confined_target(root, relative, operation="read module definition")
    if not path.is_file():
        raise CompositionError(f"missing module definition: {path}")
    # R1-1: a malformed/unreadable module definition must raise CompositionError (an AviatoError),
    # not a raw yaml.YAMLError/OSError that escapes callers guarding only AviatoError.
    try:
        path = confined_target(root, relative, operation="read module definition")
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise CompositionError(f"module definition is not valid YAML: {path}: {exc}") from exc
    except OSError as exc:
        raise CompositionError(f"could not read module definition: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CompositionError(f"module definition is not a mapping: {path}")
    _validate_mapping_keys(data, f"module definition {path}")
    return data


def _load_optional_manifest(root: Path, relative: str) -> dict[str, Any]:
    """Read a manifest that may legitimately be absent, guarded like :func:`_load_doc` (R2-3-2).

    Absent → ``{}``. A malformed/unreadable manifest raises ``CompositionError`` (an AviatoError),
    never a raw ``yaml.YAMLError``/``OSError`` that would escape callers (e.g. ``scan_fleet``) which
    guard only AviatoError — the documented R1-1 invariant, previously not applied to the pipeline
    manifest loaders.
    """
    path = confined_target(root, relative, operation="read optional manifest")
    if not path.is_file():
        return {}
    try:
        path = confined_target(root, relative, operation="read optional manifest")
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise CompositionError(f"manifest is not valid YAML: {path}: {exc}") from exc
    except OSError as exc:
        raise CompositionError(f"could not read manifest: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CompositionError(f"manifest is not a mapping: {path}")
    _validate_mapping_keys(data, f"manifest {path}")
    return data


def _confined_relpath(value: object, field: str) -> str:
    """A template module's repo-relative path, confined (N6). Reject absolute paths and `..`
    components so a malformed/hostile module manifest cannot make scaffold/proposal reads or writes
    escape the module-source tree or the consumer repo (defense-in-depth for library data)."""
    if not isinstance(value, str) or not value.strip():
        raise CompositionError(f"template module {field!r} must be a non-empty path string")
    pure = PurePosixPath(value)
    if pure.is_absolute() or value.startswith("\\") or ".." in pure.parts:
        raise CompositionError(f"template module {field!r} must be a repo-relative path without '..': {value!r}")
    return value


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CompositionError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, field)


def _strict_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise CompositionError(f"{field} must be a boolean")
    return value


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise CompositionError(f"{field} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise CompositionError(f"{field} contains duplicate identities")
    return tuple(value)


def _closed_mapping(doc: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(doc) - allowed)
    if unknown:
        raise CompositionError(
            f"{context} has unknown field(s) {unknown}; executable strings and undeclared fields "
            "are forbidden in data-only module descriptors"
        )


def _permission_pairs(value: object, field: str) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise CompositionError(f"{field} must be a permission mapping")
    pairs: list[tuple[str, str]] = []
    for key, level in value.items():
        if not isinstance(key, str) or not key or level not in {"none", "read"}:
            raise CompositionError(
                f"{field} is a top-level envelope permission ceiling; write is forbidden, only none/read are allowed"
            )
        pairs.append((key, level))
    return tuple(sorted(pairs))


def _validate_trigger_keys(value: object, context: str) -> None:
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_trigger_keys(nested, f"{context}[{index}]")
        return
    if not isinstance(value, dict):
        return
    for key, nested in value.items():
        if not isinstance(key, str) or not key.strip():
            raise CompositionError(f"{context} trigger mappings require non-empty string keys")
        _validate_trigger_keys(nested, f"{context}.{key}")


def validate_actions_job_fragment(data: object, *, context: str) -> dict[str, Any]:
    """Validate one complete GitHub Actions job at a YAML/render boundary."""

    if not isinstance(data, dict):
        raise CompositionError(f"workflow job fragment must be a YAML mapping: {context}")
    _validate_mapping_keys(data, f"workflow job fragment {context}")
    has_uses = "uses" in data
    has_steps_job = "runs-on" in data or "steps" in data
    if has_uses == has_steps_job:
        raise CompositionError(
            f"workflow job fragment must be exactly one Actions job shape: reusable 'uses' or "
            f"'runs-on' plus nonempty 'steps': {context}"
        )
    if has_uses:
        if not isinstance(data.get("uses"), str) or not data["uses"].strip():
            raise CompositionError(f"reusable Actions job 'uses' must be a non-empty string: {context}")
        return data
    if not isinstance(data.get("runs-on"), (str, list)):
        raise CompositionError(f"Actions job fragment 'runs-on' must be a string or list: {context}")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps or any(not isinstance(step, dict) for step in steps):
        raise CompositionError(f"Actions job fragment must have nonempty mapping 'steps': {context}")
    for index, step in enumerate(steps):
        selectors = [key for key in ("run", "uses") if key in step]
        if len(selectors) != 1 or not isinstance(step[selectors[0]], str) or not step[selectors[0]].strip():
            raise CompositionError(
                f"Actions job step {index} must declare exactly one non-empty string 'run' or 'uses': {context}"
            )
    return data


class Registry:
    """Loads profile/bundle/template module definitions from a source root.

    The source root is the §5.10 module-source tree: profile manifests at the
    root, ``bundles/<kind>/``, and ``scaffold/`` template modules. The registry
    maps the declarative YAML onto the :mod:`aviato.core.model` dataclasses. It
    contains no language- or deployment-specific knowledge — every such specific
    lives in the data it loads.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def library_repository(self) -> str:
        """The neutral Library repository identity supplied by packaged policy data."""
        return library_repository(load_policy(self.root))

    def profile_doc(self, name: str) -> dict[str, Any]:
        return _load_doc(self.root, f"{name}.yaml")

    def profile(self, name: str) -> Profile:
        doc = self.profile_doc(name)
        try:
            identity = doc["identity"]
            if not isinstance(identity, str) or not identity.strip():
                raise CompositionError(f"profile {name!r} identity must be a non-empty string")
            workflow_schema = doc.get("workflow_schema", 1)
            if type(workflow_schema) is not int or workflow_schema not in {1, 2}:
                raise CompositionError(f"profile {name!r} workflow_schema must be 1 or 2")
            return Profile(
                name=doc["name"],
                identity=identity,
                workflows=doc["workflows"],
                scaffold=doc["scaffold"],
                settings=doc["settings"],
                workflow_schema=workflow_schema,
            )
        except KeyError as exc:
            raise CompositionError(f"profile {name!r} missing field: {exc}") from exc

    def workflows_bundle(self, name: str) -> WorkflowsBundle:
        doc = _load_doc(self.root, f"bundles/workflows/{name}.yaml")
        return WorkflowsBundle(
            name=doc["name"],
            extends=doc.get("extends"),
            pipelines=tuple(doc.get("pipelines", ())),
            add=tuple(doc.get("add", ())),
            remove=tuple(doc.get("remove", ())),
        )

    def scaffold_bundle(self, name: str) -> ScaffoldBundle:
        doc = _load_doc(self.root, f"bundles/scaffold/{name}.yaml")
        return ScaffoldBundle(
            name=doc["name"],
            extends=doc.get("extends"),
            templates=tuple(doc.get("templates", ())),
            add=tuple(doc.get("add", ())),
            remove=tuple(doc.get("remove", ())),
        )

    def settings_bundle(self, name: str) -> SettingsBundle:
        doc = _load_doc(self.root, f"bundles/settings/{name}.yaml")
        return SettingsBundle(
            name=doc["name"],
            extends=doc.get("extends"),
            settings=dict(doc.get("settings", {})),
        )

    def security_floor(self) -> dict[str, Any]:
        """The canonical always-on security baseline (§2.13, R1-4): the ``baseline`` settings
        bundle's ``security`` block. Composition enforces that NO profile/bundle/override composes
        a repo without it. Returns ``{}`` when there is no ``baseline`` bundle (a bare test
        registry), so the floor is enforced only where the Library actually declares one. The
        canonical floor lives in DATA (baseline.yaml), so core names no specific scanner (§9b)."""
        path = confined_target(self.root, "bundles/settings/baseline.yaml", operation="read settings baseline")
        if not path.is_file():
            return {}
        return dict(self.settings_bundle("baseline").settings.get("security", {}))

    def pipeline_module(self, name: str) -> PipelineModule | None:
        """Load a typed pipeline module (§3.2/§11.3) from ``pipelines.yaml``.

        Returns None when the pipelines manifest is absent or the pipeline is not
        declared — composition tolerates this so test/empty registries still work;
        day-zero pipelines are all declared.
        """
        manifest = _load_optional_manifest(self.root, "pipelines.yaml")
        if name not in manifest:
            return None
        doc = manifest[name]
        if not isinstance(doc, dict):
            raise CompositionError(f"pipeline {name!r} descriptor must be a mapping")
        graph_module = any(key in doc for key in ("identity", "envelope", "jobs", "triggers"))
        legacy_fields = {
            "always_on",
            "privileges",
            "inputs",
            "secrets",
            "runner",
            "status_check",
            "environment",
            "environment_input",
            "code_scanning_tool",
            "reusable_privileges",
            "local_publisher_privileges",
        }
        graph_fields = {
            "identity",
            "envelope",
            "triggers",
            "jobs",
            "required_pipelines",
            "artifacts",
        }
        _closed_mapping(doc, legacy_fields | (graph_fields if graph_module else set()), f"pipeline {name!r}")
        for extra_privileges in ("reusable_privileges", "local_publisher_privileges"):
            _string_list(doc.get(extra_privileges), f"pipeline {name!r} {extra_privileges}")
        code_scanning = doc.get("code_scanning_tool")
        if code_scanning is not None:
            if not isinstance(code_scanning, dict):
                raise CompositionError(f"pipeline {name!r} code_scanning_tool must be a mapping")
            _closed_mapping(
                code_scanning,
                {"tool", "alerts_threshold", "security_alerts_threshold"},
                f"pipeline {name!r} code_scanning_tool",
            )
        if graph_module:
            pipeline_identity = _nonempty_string(doc.get("identity"), f"pipeline {name!r} identity")
            envelope = _nonempty_string(doc.get("envelope"), f"pipeline {name!r} envelope")
            always_on = _strict_bool(doc.get("always_on", False), f"pipeline {name!r} always_on")
        else:
            pipeline_identity = None
            envelope = None
            always_on = bool(doc.get("always_on", False))
        jobs_doc = doc.get("jobs", {})
        if not isinstance(jobs_doc, dict):
            raise CompositionError(f"pipeline {name!r} jobs must be a mapping")
        jobs: list[WorkflowJobModule] = []
        identities: set[str] = set()
        for job_name, job_doc in jobs_doc.items():
            if not isinstance(job_name, str) or not job_name or not isinstance(job_doc, dict):
                raise CompositionError(f"pipeline {name!r} jobs must map non-empty IDs to mappings")
            _closed_mapping(
                job_doc,
                {
                    "identity",
                    "fragment",
                    "needs",
                    "permissions",
                    "inputs",
                    "secrets",
                    "runner",
                    "environment",
                    "environment_input",
                    "status_check",
                },
                f"pipeline {name!r} job {job_name!r}",
            )
            job_identity = _nonempty_string(job_doc.get("identity"), f"pipeline {name!r} job identity")
            if job_identity in identities:
                raise CompositionError(f"pipeline {name!r} has duplicate job identity {job_identity!r}")
            identities.add(job_identity)
            job = WorkflowJobModule(
                name=job_name,
                identity=job_identity,
                fragment=_confined_relpath(job_doc.get("fragment"), "job fragment"),
                needs=_string_list(job_doc.get("needs"), f"job {job_name!r} needs"),
                permissions=_string_list(job_doc.get("permissions"), f"job {job_name!r} permissions"),
                inputs=_string_list(job_doc.get("inputs"), f"job {job_name!r} inputs"),
                secrets=_string_list(job_doc.get("secrets"), f"job {job_name!r} secrets"),
                runner=_optional_string(job_doc.get("runner"), f"job {job_name!r} runner"),
                environment=_optional_string(job_doc.get("environment"), f"job {job_name!r} environment"),
                environment_input=_optional_string(
                    job_doc.get("environment_input"), f"job {job_name!r} environment_input"
                ),
                status_check=_optional_string(job_doc.get("status_check"), f"job {job_name!r} status_check"),
            )
            # Missing, malformed, or unconfined fragments are module-schema
            # failures, not deferred render surprises.
            self.workflow_fragment(job.fragment)
            jobs.append(job)
        triggers = doc.get("triggers", {})
        if not isinstance(triggers, dict):
            raise CompositionError(f"pipeline {name!r} triggers must be a mapping")
        _validate_trigger_keys(triggers, f"pipeline {name!r}")
        return PipelineModule(
            name=name,
            privileges=_string_list(doc.get("privileges"), f"pipeline {name!r} privileges"),
            inputs=_string_list(doc.get("inputs"), f"pipeline {name!r} inputs"),
            secrets=_string_list(doc.get("secrets"), f"pipeline {name!r} secrets"),
            runner=_optional_string(doc.get("runner"), f"pipeline {name!r} runner"),
            status_check=_optional_string(doc.get("status_check"), f"pipeline {name!r} status_check"),
            always_on=always_on,
            environment=_optional_string(doc.get("environment"), f"pipeline {name!r} environment"),
            environment_input=_optional_string(doc.get("environment_input"), f"pipeline {name!r} environment_input"),
            identity=pipeline_identity,
            envelope=envelope,
            triggers=triggers,
            jobs=tuple(jobs),
            required_pipelines=_string_list(doc.get("required_pipelines"), f"pipeline {name!r} dependencies"),
            artifacts=_string_list(doc.get("artifacts"), f"pipeline {name!r} artifacts"),
            declared_aggregates=frozenset(
                set(doc)
                & {
                    "privileges",
                    "inputs",
                    "secrets",
                    "runner",
                    "status_check",
                    "environment",
                    "environment_input",
                }
            ),
        )

    def workflow_envelope(self, name: str) -> WorkflowEnvelopeModule:
        manifest = _load_optional_manifest(self.root, "workflow-envelopes.yaml")
        identities: dict[str, str] = {}
        parsed: dict[str, WorkflowEnvelopeModule] = {}
        for envelope_name, doc in manifest.items():
            if not isinstance(envelope_name, str) or not envelope_name or not isinstance(doc, dict):
                raise CompositionError("workflow envelope manifest must map non-empty IDs to mappings")
            _closed_mapping(
                doc,
                {"identity", "output_path", "name", "permissions", "concurrency"},
                f"workflow envelope {envelope_name!r}",
            )
            identity = _nonempty_string(doc.get("identity"), f"workflow envelope {envelope_name!r} identity")
            if identity in identities:
                raise CompositionError(
                    f"duplicate workflow envelope identity {identity!r}: {identities[identity]!r} and {envelope_name!r}"
                )
            identities[identity] = envelope_name
            concurrency = doc.get("concurrency", {})
            if not isinstance(concurrency, dict):
                raise CompositionError(f"workflow envelope {envelope_name!r} concurrency must be a mapping")
            concurrency_unknown = sorted(set(concurrency) - {"group", "cancel-in-progress"})
            if concurrency_unknown:
                raise CompositionError(
                    f"workflow envelope {envelope_name!r} concurrency has unknown field(s) {concurrency_unknown}"
                )
            if "group" in concurrency and not isinstance(concurrency["group"], str):
                raise CompositionError(f"workflow envelope {envelope_name!r} concurrency.group must be a string")
            cancel = concurrency.get("cancel-in-progress", False)
            if not isinstance(cancel, (bool, str)):
                raise CompositionError(
                    f"workflow envelope {envelope_name!r} concurrency.cancel-in-progress must be boolean or expression"
                )
            parsed[envelope_name] = WorkflowEnvelopeModule(
                name=envelope_name,
                identity=identity,
                output_path=_confined_relpath(doc.get("output_path"), "workflow envelope output_path"),
                display_name=_nonempty_string(doc.get("name"), f"workflow envelope {envelope_name!r} name"),
                permissions=_permission_pairs(
                    doc.get("permissions", {}), f"workflow envelope {envelope_name!r} permissions"
                ),
                concurrency=tuple(sorted(concurrency.items())),
            )
        try:
            return parsed[name]
        except KeyError as exc:
            raise CompositionError(f"missing workflow envelope {name!r}") from exc

    def workflow_fragment(self, relative: str) -> dict[str, Any]:
        relative = _confined_relpath(relative, "workflow job fragment")
        path = confined_target(self.root, relative, operation="read workflow job fragment")
        if not path.is_file():
            raise CompositionError(f"missing workflow job fragment: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise CompositionError(f"workflow job fragment is not valid YAML: {path}: {exc}") from exc
        except OSError as exc:
            raise CompositionError(f"could not read workflow job fragment: {path}: {exc}") from exc
        return validate_actions_job_fragment(data, context=str(path))

    def validate_workflow_graph_manifest(self) -> None:
        """Validate every graph identity and fragment, including unselected modules."""

        identities: dict[str, str] = {}

        def record(identity: str, owner: str) -> None:
            if identity in identities:
                raise CompositionError(
                    f"duplicate {owner.split()[0]} identity {identity!r}: {identities[identity]} and {owner}"
                )
            identities[identity] = owner

        envelope_manifest = _load_optional_manifest(self.root, "workflow-envelopes.yaml")
        for envelope_name in sorted(envelope_manifest):
            envelope = self.workflow_envelope(envelope_name)
            record(envelope.identity, f"workflow envelope {envelope.name!r}")

        pipeline_manifest = _load_optional_manifest(self.root, "pipelines.yaml")
        for pipeline_name, descriptor in pipeline_manifest.items():
            if not isinstance(pipeline_name, str) or not pipeline_name.strip() or not isinstance(descriptor, dict):
                raise CompositionError("pipeline manifest must map non-empty string IDs to descriptor mappings")
        for pipeline_name in sorted(pipeline_manifest):
            module = self.pipeline_module(pipeline_name)
            if module is None or module.identity is None:
                continue
            record(module.identity, f"pipeline {pipeline_name!r}")
            for job in module.jobs:
                record(job.identity, f"job {pipeline_name!r}/{job.name!r}")

    def always_on_pipelines(self) -> tuple[str, ...]:
        """Pipelines the data flags ``always_on`` — they must survive every composition (§2.13)."""
        manifest = _load_optional_manifest(self.root, "pipelines.yaml")
        return tuple(name for name, doc in manifest.items() if isinstance(doc, dict) and doc.get("always_on"))

    def declared_pipelines(self) -> set[str] | None:
        """The set of pipeline names the manifest declares, or None when no manifest exists (§5.1).

        Returns None — not an empty set — when ``pipelines.yaml`` is absent, so composition can
        distinguish "this registry declares pipelines, validate refs against them" from a bare
        test/empty registry that declares none (which stays lenient). The day-zero Library has a
        complete manifest, so an unknown pipeline ref there is a typo and must hard-error (§5.1).
        """
        path = confined_target(self.root, "pipelines.yaml", operation="read pipeline manifest")
        if not path.is_file():
            return None  # absent → None (distinct from an empty manifest); see docstring
        return {
            name for name, doc in _load_optional_manifest(self.root, "pipelines.yaml").items() if isinstance(doc, dict)
        }

    def template_module(self, name: str) -> TemplateModule:
        doc = _load_doc(self.root, f"scaffold/{name}.yaml")
        return TemplateModule(
            identity=f"artifact/{_nonempty_string(doc.get('name', name), f'template {name!r} name')}/v1",
            output_path=_confined_relpath(doc.get("output_path"), "output_path"),
            source=_confined_relpath(doc.get("source"), "source"),
            seed_once=bool(doc.get("seed_once", False)),
            comment=doc.get("comment"),
            required_variables=tuple(doc.get("required_variables", ())),
            when=tuple(sorted((str(k), str(v)) for k, v in (doc.get("when") or {}).items())),
            legacy_aliases=tuple(
                _confined_relpath(alias, f"template {name!r} legacy alias")
                for alias in _string_list(doc.get("legacy_aliases", []), f"template {name!r} legacy aliases")
            ),
        )

    def template_body(self, module: TemplateModule) -> str:
        """Read a template module's raw source body from the module-source tree."""
        relative = f"scaffold/{module.source}"
        path = confined_target(self.root, relative, operation="read template source")
        if not path.is_file():
            raise CompositionError(f"missing template source: {path}")
        path = confined_target(self.root, relative, operation="read template source")
        return path.read_text(encoding="utf-8")
