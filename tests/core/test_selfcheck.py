from __future__ import annotations

from pathlib import Path

from aviato.core.selfcheck import (
    core_import_violations,
    denylist_violations,
    load_denylist,
)
from aviato.paths import DENYLIST_FILE


def test_denylist_is_the_maintained_list() -> None:
    denylist = load_denylist(DENYLIST_FILE)
    assert "ruff" in denylist
    assert "docusaurus" in denylist
    assert "app store" in denylist
    # Consumer-target format/language identifiers that must never re-enter core
    # (version-source rewriters and the typecheck-variant rule live in plug-ins).
    for token in ("javascript", "typescript", "package.json", "pbxproj", "plist", "pyproject"):
        assert token in denylist


def test_core_does_not_name_the_python_project_manifest() -> None:
    # §9b: the Python project manifest name (pyproject) must not be hardcoded in core;
    # detection of the Library is structural, not by a language-specific filename.
    assert denylist_violations(denylist={"pyproject"}) == []


def test_core_has_no_import_edge_into_plugin_tree() -> None:
    assert core_import_violations() == []


def test_core_contains_no_denylisted_identifier() -> None:
    assert denylist_violations() == []


def test_import_edge_detected_in_synthetic_core(tmp_path: Path) -> None:
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "bad.py").write_text("from aviato.plugins import comment_syntax\n")
    assert core_import_violations(fake_core) != []


def test_denylisted_token_detected_in_synthetic_core(tmp_path: Path) -> None:
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "bad.py").write_text("ENGINE = 'docusaurus'\n")
    assert denylist_violations(fake_core, {"docusaurus"}) != []


def test_dynamic_import_edge_detected_in_synthetic_core(tmp_path: Path) -> None:
    # §9b: a string-assembled dynamic import of the plug-in tree (the exact evasion a
    # line-regex would miss) must still be caught by the import-edge check.
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "sneaky.py").write_text("import importlib\nmod = importlib.import_module('aviato.' + 'plugins')\n")
    assert core_import_violations(fake_core) != []


def test_relative_import_edge_detected_in_synthetic_core(tmp_path: Path) -> None:
    # A relative `from ..plugins import x` reaches the same plug-in tree and must be caught.
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "rel.py").write_text("from ..plugins import comment_syntax\n")
    assert core_import_violations(fake_core) != []


def test_comment_mentioning_plugin_tree_does_not_trip(tmp_path: Path) -> None:
    # A prose mention of the plug-in package in a comment is not an import edge.
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "ok.py").write_text("# see aviato.plugins.comment_syntax for the mapping\nX = 1\n")
    assert core_import_violations(fake_core) == []


def test_substring_does_not_falsely_trip(tmp_path: Path) -> None:
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    # "nodes" contains "node" but is a different word; boundaries must not trip it
    (fake_core / "ok.py").write_text("graph_nodes = []\n")
    assert denylist_violations(fake_core, {"node"}) == []
