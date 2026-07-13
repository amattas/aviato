from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def _write(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture
def module_root(tmp_path: Path) -> Path:
    """A minimal module-source tree: a base + child profile composing all kinds.

    child workflows: base [a, b] + add [c] - remove [a]  -> [b, c]
    child settings:  base {pr:{required_reviews:2, dismiss:true}} override required_reviews:1
    """
    root = tmp_path / "modsrc"

    _write(root / "bundles" / "workflows" / "base-wf.yaml", {"name": "base-wf", "pipelines": ["a", "b"]})
    _write(
        root / "bundles" / "workflows" / "child-wf.yaml",
        {"name": "child-wf", "extends": "base-wf", "add": ["c"], "remove": ["a"]},
    )

    _write(
        root / "bundles" / "scaffold" / "child-sc.yaml",
        {"name": "child-sc", "templates": ["cfg"]},
    )
    _write(
        root / "scaffold" / "cfg.yaml",
        {"name": "cfg", "output_path": "cfg.py", "source": "cfg.py.tmpl", "comment": "#"},
    )

    _write(
        root / "bundles" / "settings" / "base-set.yaml",
        {"name": "base-set", "settings": {"pr": {"required_reviews": 2, "dismiss_stale": True}}},
    )
    _write(
        root / "bundles" / "settings" / "child-set.yaml",
        {"name": "child-set", "extends": "base-set", "settings": {"pr": {"required_reviews": 1}}},
    )

    _write(
        root / "child.yaml",
        {
            "name": "child",
            "identity": "aviato-profile/child/v1",
            "workflows": "child-wf",
            "scaffold": "child-sc",
            "settings": "child-set",
            "variables": [{"name": "dist", "type": "string"}],
            "version_source": {"locations": ["pyproject.toml"]},
            "toolchain": {"engine": "x"},
            "docs_pipeline": "docs-pages",
        },
    )
    return root
