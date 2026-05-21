from __future__ import annotations

from pathlib import Path

import pytest

from aviato.core.errors import CompositionError
from aviato.core.model import Profile, ScaffoldBundle, SettingsBundle, TemplateModule, WorkflowsBundle
from aviato.core.registry import Registry


def test_loads_profile(module_root: Path) -> None:
    profile = Registry(module_root).profile("child")
    assert isinstance(profile, Profile)
    assert profile.workflows == "child-wf"
    assert profile.requires_macos is False


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
