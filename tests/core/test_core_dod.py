from __future__ import annotations

from pathlib import Path

import pytest

from aviato.core.composition import resolve_profile
from aviato.core.errors import CompositionError
from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT


def test_core_resolution_machinery_runs_with_zero_plugins(tmp_path: Path) -> None:
    # §9(a): the core loads and its machinery runs with no plug-in data present.
    empty = tmp_path / "empty"
    empty.mkdir()
    reg = Registry(empty)
    with pytest.raises(CompositionError):
        resolve_profile(reg, "anything")


def test_core_modules_import_without_loading_plugin_tree() -> None:
    # §9b(a): importing every aviato.core module must NOT pull in the plug-in tree —
    # the core has no import-time dependency on day-zero plug-ins. Run in a clean
    # subprocess so other tests' imports don't pollute the module graph.
    import subprocess
    import sys

    code = (
        "import importlib, pkgutil, sys\n"
        "import aviato.core as c\n"
        "for m in pkgutil.iter_modules(c.__path__, 'aviato.core.'):\n"
        "    importlib.import_module(m.name)\n"
        "leaked = sorted(k for k in sys.modules if k == 'aviato.plugins' or k.startswith('aviato.plugins.'))\n"
        "assert not leaked, leaked\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_same_core_drives_two_unrelated_plugins() -> None:
    # §9(c): the same unmodified core drives at least two unrelated plug-ins.
    reg = Registry(MODULE_SOURCE_ROOT)
    a = resolve_profile(reg, "python-library")  # python language + PyPI deploy
    b = resolve_profile(reg, "swift-app")  # swift language + App Store Connect deploy
    assert a.profile != b.profile
    assert a.pipelines and b.pipelines
    # the two plug-ins are genuinely unrelated: disjoint deploy pipelines
    assert set(a.pipelines) != set(b.pipelines)
