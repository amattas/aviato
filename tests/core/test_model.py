from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from aviato.core.model import (
    FrozenDict,
    PipelineModule,
    Profile,
    ResolvedSet,
    ScaffoldBundle,
    SettingsBundle,
    TemplateModule,
    VariableSpec,
    VersionSourceModule,
    WorkflowEnvelopeModule,
    WorkflowJobModule,
    WorkflowsBundle,
)


def test_frozen_dict_never_string_coerces_non_string_keys() -> None:
    values: Any = {1: "numeric"}
    with pytest.raises(TypeError, match="string keys"):
        FrozenDict(values)


def test_variable_spec_defaults_non_secret_and_required() -> None:
    v = VariableSpec(name="dist", type="string")
    assert v.secret is False
    assert v.required is True
    assert v.domain is None


def test_enum_variable_carries_domain() -> None:
    v = VariableSpec(name="language-variant", type="enum", domain=("typescript", "javascript"))
    assert v.domain == ("typescript", "javascript")


def test_template_module_seed_once_default_false() -> None:
    t = TemplateModule(output_path="cfg.py", source="cfg.py.j2")
    assert t.seed_once is False
    assert t.required_variables == ()


def test_pipeline_module_declares_privileges() -> None:
    p = PipelineModule(name="pypi", privileges=("id-token: write", "contents: read"))
    assert "id-token: write" in p.privileges


def test_workflow_graph_modules_are_frozen_and_carry_stable_identity() -> None:
    envelope = WorkflowEnvelopeModule(
        name="ci",
        identity="workflow/ci/v1",
        output_path=".github/workflows/ci.yml",
        display_name="CI",
    )
    job = WorkflowJobModule(
        name="verify",
        identity="job/verify/v1",
        fragment="workflow-fragments/verify.yml",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        envelope.identity = "changed"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        job.fragment = "changed"  # type: ignore[misc]


def test_profile_is_frozen() -> None:
    p = Profile(name="x", identity="aviato-profile/x/v1", workflows="w", scaffold="s", settings="g")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.name = "y"  # type: ignore[misc]


def test_bundle_fields_present() -> None:
    wb = WorkflowsBundle(name="w", extends="base", add=("verify",), remove=())
    sb = ScaffoldBundle(name="s", templates=("a", "b"))
    gb = SettingsBundle(name="g", settings={"pr": {"required_reviews": 1}})
    assert wb.extends == "base"
    assert sb.templates == ("a", "b")
    assert gb.settings["pr"]["required_reviews"] == 1


def test_resolved_set_holds_composed_modules() -> None:
    rs = ResolvedSet(
        profile="x",
        pipelines=("verify",),
        templates=(TemplateModule(output_path="c", source="c.j2"),),
        settings={"pr": {}},
        variables=(VariableSpec(name="n", type="string"),),
        version_source=VersionSourceModule(locations=("pyproject.toml",)),
        toolchain={},
    )
    assert rs.pipelines == ("verify",)
    assert rs.version_source is not None
    assert rs.version_source.locations == ("pyproject.toml",)


def test_resolved_sets_compare_by_value() -> None:
    def build() -> ResolvedSet:
        return ResolvedSet(
            profile="x",
            pipelines=("verify",),
            templates=(),
            settings={"a": 1},
            variables=(),
            version_source=None,
            toolchain={},
        )

    assert build() == build()
