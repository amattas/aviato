from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from aviato.core.compiler import (
    DesiredState,
    compile_desired_state,
    compile_partial_desired_state,
    require_workflow_schema_v2,
)
from aviato.core.composition import resolve_profile
from aviato.core.errors import CompositionError
from aviato.core.model import Unknown
from aviato.core.onboarding import materialize_items
from aviato.core.registry import Registry


def _write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _registry(tmp_path: Path) -> Registry:
    root = tmp_path / "library"
    _write_yaml(root / "policy.yml", {"library": {"repository": "example/library"}})
    _write_yaml(
        root / "demo.yaml",
        {
            "name": "demo",
            "identity": "aviato-profile/demo/v2",
            "workflow_schema": 2,
            "workflows": "demo-wf",
            "scaffold": "demo-sc",
            "settings": "demo-set",
            "variables": [
                {"name": "variant", "type": "enum", "domain": ["a", "b"]},
                {"name": "environment-name", "type": "string", "required": False},
                {"name": "owner", "type": "string", "required": False},
                {"name": "repo", "type": "string", "required": False},
            ],
        },
    )
    _write_yaml(
        root / "bundles/workflows/demo-wf.yaml",
        {"name": "demo-wf", "pipelines": ["baseline", "verify", "release"]},
    )
    _write_yaml(
        root / "bundles/scaffold/demo-sc.yaml",
        {"name": "demo-sc", "templates": ["base", "variant-a", "variant-b"]},
    )
    _write_yaml(
        root / "bundles/settings/demo-set.yaml",
        {
            "name": "demo-set",
            "settings": {
                "default_branch": {"required_status_checks": []},
                "security": {},
            },
        },
    )
    for name, output, when in (
        ("base", "README.md", {}),
        ("variant-a", "variant.txt", {"variant": "a"}),
        ("variant-b", "variant.txt", {"variant": "b"}),
        ("release-artifact", "release.yml", {}),
    ):
        _write_yaml(
            root / f"scaffold/{name}.yaml",
            {"output_path": output, "source": f"files/{name}.j2", "when": when},
        )
        source = root / f"scaffold/files/{name}.j2"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"{name}\n", encoding="utf-8")
    _write_yaml(
        root / "workflow-envelopes.yaml",
        {
            "ci": {
                "identity": "workflow/ci/v1",
                "output_path": ".github/workflows/ci.yml",
                "name": "CI",
                "permissions": {},
                "concurrency": {"group": "ci-${{ github.ref }}", "cancel-in-progress": True},
            },
            "release": {
                "identity": "workflow/release/v1",
                "output_path": ".github/workflows/release.yml",
                "name": "Release",
                "permissions": {"contents": "read"},
            },
        },
    )
    _write_yaml(
        root / "pipelines.yaml",
        {
            "baseline": {
                "identity": "pipeline/baseline/v1",
                "envelope": "ci",
                "always_on": True,
                "privileges": ["contents: read"],
                "runner": "ubuntu-latest",
                "status_check": "CI / Security",
                "triggers": {"pull_request": {}},
                "jobs": {
                    "security": {
                        "identity": "job/security/v1",
                        "fragment": "workflow-fragments/security.yml",
                        "permissions": ["contents: read"],
                        "runner": "ubuntu-latest",
                        "status_check": "CI / Security",
                    }
                },
            },
            "verify": {
                "identity": "pipeline/verify/v1",
                "envelope": "ci",
                "triggers": {"push": {"branches": {"add": ["main"]}}},
                "required_pipelines": ["baseline"],
                "privileges": ["contents: read"],
                "inputs": ["variant"],
                "runner": "ubuntu-latest",
                "status_check": "CI / Verify",
                "jobs": {
                    "verify": {
                        "identity": "job/verify/v1",
                        "fragment": "workflow-fragments/verify.yml",
                        "needs": ["security"],
                        "permissions": ["contents: read"],
                        "inputs": ["variant"],
                        "runner": "ubuntu-latest",
                        "status_check": "CI / Verify",
                    }
                },
            },
            "release": {
                "identity": "pipeline/release/v1",
                "envelope": "release",
                "triggers": {"push": {"tags": {"add": ["v*"]}}},
                "required_pipelines": ["verify"],
                "artifacts": ["release-artifact"],
                "privileges": ["contents: read"],
                "secrets": ["TOKEN"],
                "runner": "ubuntu-latest",
                "environment_input": "environment-name",
                "jobs": {
                    "publish": {
                        "identity": "job/publish/v1",
                        "fragment": "workflow-fragments/publish.yml",
                        "permissions": ["contents: read"],
                        "secrets": ["TOKEN"],
                        "runner": "ubuntu-latest",
                        "environment_input": "environment-name",
                    }
                },
            },
        },
    )
    _write_yaml(
        root / "workflow-fragments/security.yml",
        {
            "name": "Security",
            "runs-on": "ubuntu-latest",
            "permissions": {"contents": "read"},
            "steps": [{"run": "echo secure"}],
        },
    )
    _write_yaml(
        root / "workflow-fragments/verify.yml",
        {
            "name": "Verify",
            "runs-on": "ubuntu-latest",
            "needs": ["security"],
            "permissions": {"contents": "read"},
            "steps": [{"run": "echo ${{ inputs.variant }}"}],
        },
    )
    _write_yaml(
        root / "workflow-fragments/publish.yml",
        {
            "name": "Publish",
            "runs-on": "ubuntu-latest",
            "permissions": {"contents": "read"},
            # Pipeline-owned variables use the engine's render placeholder. A
            # GitHub `inputs.*` expression here would be invalid for this
            # push/tag-triggered local job and would not bind the selected value.
            "environment": "{{ environment-name }}",
            "steps": [{"run": "echo ${{ secrets.TOKEN }}"}],
        },
    )
    return Registry(root)


def _exact(registry: Registry, **overrides: Any) -> DesiredState:
    resolved = resolve_profile(registry, "demo", overrides=overrides or None)
    return compile_desired_state(
        registry,
        resolved,
        {"variant": "a", "environment-name": "production"},
        pin="1.2.3",
    )


def test_selected_pipeline_contributes_triggers_jobs_checks_and_artifacts(tmp_path: Path) -> None:
    desired = _exact(_registry(tmp_path))
    assert all(yaml.safe_load(workflow.body) == workflow.document for workflow in desired.workflows)
    workflows = {workflow.output_path: workflow.document for workflow in desired.workflows}
    assert set(workflows[".github/workflows/ci.yml"]["jobs"]) == {"security", "verify"}
    assert workflows[".github/workflows/ci.yml"]["on"] == {
        "pull_request": {},
        "push": {"branches": ["main"]},
    }
    assert desired.required_status_checks == ("CI / Security", "CI / Verify")
    assert "release.yml" in {artifact.output_path for artifact in desired.artifacts}
    assert desired.environments == ("production",)


def test_pipeline_removal_removes_its_jobs_triggers_checks_privileges_and_artifacts(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    desired = _exact(registry, pipelines={"remove": ["release"]})
    paths = {artifact.output_path for artifact in desired.artifacts}
    assert ".github/workflows/release.yml" not in paths
    assert "release.yml" not in paths
    assert desired.environments == ()
    assert desired.privileges == ("contents: read",)
    assert all("tags" not in str(workflow.document["on"]) for workflow in desired.workflows)


def test_scaffold_templates_are_base_union_selected_pipeline_artifacts(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    desired = _exact(registry)
    assert {artifact.output_path for artifact in desired.artifacts} >= {
        "README.md",
        "variant.txt",
        "release.yml",
    }
    release_artifact = next(artifact for artifact in desired.artifacts if artifact.output_path == "release.yml")
    assert release_artifact.owners == ("pipeline/release/v1",)
    assert "release.yml" not in {
        artifact.output_path for artifact in _exact(registry, pipelines={"remove": ["release"]}).artifacts
    }


def test_compiler_is_deterministic_for_equivalent_input_order(tmp_path: Path) -> None:
    first = _exact(_registry(tmp_path))
    second = compile_desired_state(
        _registry(tmp_path),
        resolve_profile(_registry(tmp_path), "demo"),
        {"environment-name": "production", "variant": "a"},
        pin="1.2.3",
    )
    assert first == second
    mutable: Any = first
    with pytest.raises(dataclasses.FrozenInstanceError):
        mutable.profile = "other"


def test_graph_models_and_desired_state_are_deeply_immutable(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    resolved = resolve_profile(registry, "demo")
    desired = _exact(registry)
    resolved_settings: Any = resolved.settings
    resolved_triggers: Any = resolved.pipeline_modules[0].triggers
    desired_settings: Any = desired.settings
    workflow_document: Any = desired.workflows[0].document
    with pytest.raises(TypeError):
        resolved_settings["security"]["enabled"] = True
    with pytest.raises(TypeError):
        resolved_triggers["pull_request"]["types"] = ["opened"]
    with pytest.raises(TypeError):
        desired_settings["default_branch"]["required_status_checks"] = []
    with pytest.raises(TypeError):
        workflow_document["jobs"]["security"]["steps"].append({"run": "pwn"})


def test_compiler_rejects_duplicate_jobs_paths_and_incompatible_triggers(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["release"]["jobs"]["verify"] = manifest["release"]["jobs"].pop("publish")
    _write_yaml(registry.root / "pipelines.yaml", manifest)
    with pytest.raises(CompositionError, match="duplicate job"):
        _exact(registry)

    registry = _registry(tmp_path / "path")
    envelopes = yaml.safe_load((registry.root / "workflow-envelopes.yaml").read_text())
    envelopes["release"]["output_path"] = ".github/workflows/ci.yml"
    _write_yaml(registry.root / "workflow-envelopes.yaml", envelopes)
    with pytest.raises(CompositionError, match="duplicate.*path"):
        _exact(registry)

    registry = _registry(tmp_path / "trigger")
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["baseline"]["triggers"] = {"push": {"branches-ignore": True}}
    manifest["verify"]["triggers"] = {"push": {"branches-ignore": False}}
    _write_yaml(registry.root / "pipelines.yaml", manifest)
    with pytest.raises(CompositionError, match="trigger"):
        _exact(registry)


def test_compiler_rejects_missing_needs_and_pipeline_dependencies(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["verify"]["jobs"]["verify"]["needs"] = ["ghost"]
    fragment = yaml.safe_load((registry.root / "workflow-fragments/verify.yml").read_text())
    fragment["needs"] = ["ghost"]
    _write_yaml(registry.root / "pipelines.yaml", manifest)
    _write_yaml(registry.root / "workflow-fragments/verify.yml", fragment)
    with pytest.raises(CompositionError, match="needs"):
        _exact(registry)

    registry = _registry(tmp_path / "dependency")
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["baseline"]["required_pipelines"] = ["ghost"]
    _write_yaml(registry.root / "pipelines.yaml", manifest)
    with pytest.raises(CompositionError, match="required pipeline"):
        _exact(registry)


def test_trigger_list_deltas_and_dependency_cycles_are_validated(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["baseline"]["triggers"] = {"push": {"branches": {"add": ["main"]}}}
    manifest["verify"]["triggers"] = {"push": {"branches": {"remove": ["main"], "add": ["develop"]}}}
    _write_yaml(registry.root / "pipelines.yaml", manifest)
    desired = _exact(registry)
    ci = next(workflow for workflow in desired.workflows if workflow.envelope == "ci")
    assert ci.document["on"]["push"]["branches"] == ["develop"]
    resolved = resolve_profile(registry, "demo")
    reversed_resolved = replace(
        resolved,
        pipelines=tuple(reversed(resolved.pipelines)),
        pipeline_modules=tuple(reversed(resolved.pipeline_modules)),
    )
    reversed_desired = compile_desired_state(
        registry,
        reversed_resolved,
        {"variant": "a", "environment-name": "production"},
        pin="1.2.3",
    )
    reversed_ci = next(workflow for workflow in reversed_desired.workflows if workflow.envelope == "ci")
    assert reversed_ci.document["on"] == ci.document["on"]

    manifest["verify"]["triggers"] = {"push": {"branches": {"remove": ["ghost"]}}}
    _write_yaml(registry.root / "pipelines.yaml", manifest)
    with pytest.raises(CompositionError, match="orphaned trigger removal"):
        _exact(registry)

    registry = _registry(tmp_path / "cycle")
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["baseline"]["required_pipelines"] = ["release"]
    _write_yaml(registry.root / "pipelines.yaml", manifest)
    with pytest.raises(CompositionError, match="cyclic required-pipeline"):
        _exact(registry)


def test_compiler_rejects_orphaned_checks_permissions_inputs_secrets_and_environments(tmp_path: Path) -> None:
    mutations: dict[str, Callable[[dict[str, Any]], None]] = {
        "status check": lambda doc: doc["baseline"]["jobs"]["security"].__setitem__("status_check", "CI / Ghost"),
        "permissions": lambda doc: doc["baseline"]["jobs"]["security"].__setitem__("permissions", ["issues: write"]),
        "inputs": lambda doc: doc["verify"]["jobs"]["verify"].__setitem__("inputs", ["missing"]),
        "secrets": lambda doc: doc["release"]["jobs"]["publish"].__setitem__("secrets", ["OTHER"]),
        "environment": lambda doc: doc["release"]["jobs"]["publish"].__setitem__("environment", "other"),
    }
    for index, (message, mutate) in enumerate(mutations.items()):
        registry = _registry(tmp_path / str(index))
        manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
        mutate(manifest)
        _write_yaml(registry.root / "pipelines.yaml", manifest)
        with pytest.raises(CompositionError, match=message):
            _exact(registry)


@pytest.mark.parametrize("selector", ["run", "uses"])
def test_compiler_revalidates_actions_step_selectors_after_rendering(tmp_path: Path, selector: str) -> None:
    registry = _registry(tmp_path)
    fragment = yaml.safe_load((registry.root / "workflow-fragments/security.yml").read_text())
    fragment["steps"] = [{selector: "{{ owner }}"}]
    _write_yaml(registry.root / "workflow-fragments/security.yml", fragment)

    with pytest.raises(CompositionError, match="step.*run.*uses|run.*uses"):
        compile_desired_state(
            registry,
            resolve_profile(registry, "demo"),
            {"variant": "a", "environment-name": "production", "owner": ""},
            pin="1.2.3",
        )


def test_v2_pipeline_compatibility_aggregate_metadata_is_optional(tmp_path: Path) -> None:
    fields = ("privileges", "inputs", "secrets", "runner", "status_check", "environment_input")
    owners = ("baseline", "verify", "release", "baseline", "baseline", "release")
    for index, (field, owner) in enumerate(zip(fields, owners, strict=True)):
        registry = _registry(tmp_path / str(index))
        manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
        manifest[owner].pop(field, None)
        _write_yaml(registry.root / "pipelines.yaml", manifest)
        desired = _exact(registry)
        assert desired.workflows


def test_compiler_rejects_removal_of_an_always_on_pipeline(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(CompositionError, match="always-on"):
        _exact(registry, pipelines={"remove": ["baseline"]})


def test_compiler_rejects_workflow_privilege_broader_than_selected_graph(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    envelopes = yaml.safe_load((registry.root / "workflow-envelopes.yaml").read_text())
    envelopes["ci"]["permissions"] = {"issues": "write"}
    _write_yaml(registry.root / "workflow-envelopes.yaml", envelopes)
    with pytest.raises(CompositionError, match="broader|ceiling"):
        _exact(registry)


def test_envelope_permissions_are_never_write_even_when_jobs_need_write(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["release"]["privileges"] = ["contents: write"]
    manifest["release"]["jobs"]["publish"]["permissions"] = ["contents: write"]
    fragment = yaml.safe_load((registry.root / "workflow-fragments/publish.yml").read_text())
    fragment["permissions"] = {"contents": "write"}
    envelopes = yaml.safe_load((registry.root / "workflow-envelopes.yaml").read_text())
    envelopes["release"]["permissions"] = {"contents": "write"}
    _write_yaml(registry.root / "pipelines.yaml", manifest)
    _write_yaml(registry.root / "workflow-fragments/publish.yml", fragment)
    _write_yaml(registry.root / "workflow-envelopes.yaml", envelopes)
    with pytest.raises(CompositionError, match="envelope.*write|top-level.*write"):
        _exact(registry)


def test_legacy_workflow_schema_is_read_only_and_v2_is_required_for_graph_mutation(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    profile = yaml.safe_load((registry.root / "demo.yaml").read_text())
    profile.pop("workflow_schema")
    _write_yaml(registry.root / "demo.yaml", profile)
    resolved = resolve_profile(registry, "demo")
    assert resolved.workflow_schema == 1
    with pytest.raises(CompositionError, match="repin"):
        require_workflow_schema_v2(resolved, operation="sync")
    with pytest.raises(CompositionError, match="workflow schema v2"):
        compile_desired_state(registry, resolved, {"variant": "a"}, pin="1.2.3")
    with pytest.raises(CompositionError, match="repin"):
        materialize_items(registry, "demo", {"variant": "a"}, pin="1.2.3")


def test_v2_materialization_uses_the_compiled_graph_artifact_set(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    items = materialize_items(
        registry,
        "demo",
        {"variant": "a", "environment-name": "production"},
        pin="1.2.3",
    )

    outputs = {item.output for item in items}
    assert outputs >= {
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        "README.md",
        "release.yml",
        "variant.txt",
    }


def _add_distinct_audit_job(registry: Registry, *, retain_scalar_aggregates: bool) -> None:
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    baseline = manifest["baseline"]
    if not retain_scalar_aggregates:
        baseline.pop("runner")
        baseline.pop("status_check")
    baseline["jobs"]["audit"] = {
        "identity": "job/audit/v1",
        "fragment": "workflow-fragments/audit.yml",
        "permissions": ["contents: read"],
        "runner": "macos-latest",
        "environment": "audit-lab",
        "status_check": "CI / Audit",
    }
    _write_yaml(registry.root / "pipelines.yaml", manifest)
    _write_yaml(
        registry.root / "workflow-fragments/audit.yml",
        {
            "name": "Audit",
            "runs-on": "macos-latest",
            "permissions": {"contents": "read"},
            "environment": "audit-lab",
            "steps": [{"run": "echo audit"}],
        },
    )


def test_multi_job_pipeline_derives_distinct_runners_checks_and_settings_from_jobs(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _add_distinct_audit_job(registry, retain_scalar_aggregates=False)

    desired = _exact(registry)

    ci = next(workflow for workflow in desired.workflows if workflow.envelope == "ci")
    assert set(ci.document["jobs"]) == {"audit", "security", "verify"}
    assert desired.required_status_checks == ("CI / Audit", "CI / Security", "CI / Verify")
    assert desired.environments == ("audit-lab", "production")
    assert desired.settings["default_branch"]["required_status_checks"] == [
        "CI / Audit",
        "CI / Security",
        "CI / Verify",
    ]
    resolved = resolve_profile(registry, "demo")
    assert resolved.settings["default_branch"]["required_status_checks"] == [
        "CI / Audit",
        "CI / Security",
        "CI / Verify",
    ]
    from aviato.cli import _deployment_environments

    assert _deployment_environments(resolved, {"environment-name": "production"}) == (
        "audit-lab",
        "production",
    )


def test_multi_job_pipeline_rejects_unrepresentative_provided_scalar_aggregate(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _add_distinct_audit_job(registry, retain_scalar_aggregates=True)

    with pytest.raises(CompositionError, match="runner.*multiple|aggregate runner"):
        _exact(registry)


def test_partial_preview_lists_definite_and_conditional_outputs(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    partial = compile_partial_desired_state(
        registry,
        resolve_profile(registry, "demo"),
        {"variant": Unknown, "environment-name": Unknown},
        pin="1.2.3",
    )
    assert "README.md" in partial.definite_artifacts
    assert "variant.txt" in partial.conditional_artifacts
    assert "production" not in partial.definite_environments
    assert "environment-name" in partial.missing_inputs
    assert partial.definite_status_checks == ("CI / Security", "CI / Verify")


def test_partial_preview_never_has_an_applicable_plan_id(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    partial = compile_partial_desired_state(
        registry,
        resolve_profile(registry, "demo"),
        {"variant": Unknown, "environment-name": Unknown},
        pin="1.2.3",
    )
    assert partial.applicable_plan_id is None
    assert partial.applicable is False


def test_partial_preview_validates_unknown_keys_before_preserving_unknowns(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(CompositionError, match="typo"):
        compile_partial_desired_state(
            registry,
            resolve_profile(registry, "demo"),
            {"variant": Unknown, "typo": Unknown},
            pin="1.2.3",
        )


def test_exact_desired_state_requires_complete_typed_variables(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    resolved = resolve_profile(registry, "demo")
    with pytest.raises(CompositionError, match="complete typed variables"):
        compile_desired_state(registry, resolved, {"variant": Unknown}, pin="1.2.3")
    with pytest.raises(CompositionError, match="complete typed variables"):
        compile_desired_state(registry, resolved, {"variant": "invalid"}, pin="1.2.3")


def test_exact_desired_state_preserves_profile_variable_constraints(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    profile = yaml.safe_load((registry.root / "demo.yaml").read_text())
    profile["variable_constraints"] = {"any_of": [["owner", "repo"]]}
    _write_yaml(registry.root / "demo.yaml", profile)

    with pytest.raises(CompositionError, match="requires at least one"):
        _exact(registry)


def test_cli_v2_partial_preview_is_conditional_and_non_applicable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aviato import cli

    registry = _registry(tmp_path)
    snapshot = SimpleNamespace(registry=registry, policy_root=registry.root)
    monkeypatch.setattr(cli, "_open_published_snapshot", lambda _pin: snapshot)
    monkeypatch.setattr("aviato.rulesets.render_all_rulesets", lambda **_kwargs: [])

    assert cli.main(["onboard", "owner/repo", "--profile", "demo", "--pin", "1.2.3"]) == 0
    output = capsys.readouterr().out
    assert "variant.txt (conditional)" in output
    assert "definite settings:" in output
    assert "conditional settings:" in output
    assert "definite environments:" in output
    assert "conditional environments:" in output
    assert "definite status checks:" in output
    assert "conditional status checks:" in output
    assert "plan id" not in output.lower()
    assert "missing inputs:" in output


def test_cli_onboard_reports_non_string_nested_settings_key_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aviato import cli

    registry = _registry(tmp_path)
    settings_path = registry.root / "bundles/settings/demo-set.yaml"
    settings = yaml.safe_load(settings_path.read_text())
    settings["settings"]["security"] = {1: True}
    _write_yaml(settings_path, settings)
    snapshot = SimpleNamespace(registry=registry, policy_root=registry.root)
    monkeypatch.setattr(cli, "_open_published_snapshot", lambda _pin: snapshot)

    assert cli.main(["onboard", "owner/repo", "--profile", "demo", "--pin", "1.2.3"]) == 2
    error = capsys.readouterr().err
    assert "mapping" in error
    assert "string key" in error
