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


def test_substring_does_not_falsely_trip(tmp_path: Path) -> None:
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    # "nodes" contains "node" but is a different word; boundaries must not trip it
    (fake_core / "ok.py").write_text("graph_nodes = []\n")
    assert denylist_violations(fake_core, {"node"}) == []
