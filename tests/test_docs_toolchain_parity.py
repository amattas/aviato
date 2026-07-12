from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from aviato.paths import REPO_ROOT


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docs_toolchain_source_has_all_exact_pins() -> None:
    data = yaml.safe_load((REPO_ROOT / "aviato/library/docs-toolchain.yaml").read_text(encoding="utf-8"))
    assert data == {
        "zensical": "0.0.50",
        "mike": "git+https://github.com/squidfunk/mike.git@2d4ad799442f4592db8ad53b179bfb33db8c69ac",
        "pydoc-markdown": "4.8.2",
    }


def test_docs_pin_sync_declares_exactly_three_outputs_and_detects_all_drift(tmp_path: Path) -> None:
    sync = _load_script("sync-docs-toolchain-pins.py")
    root = tmp_path / "repo"
    (root / "aviato/library").mkdir(parents=True)
    (root / "aviato/library/docs-toolchain.yaml").write_text(
        (REPO_ROOT / "aviato/library/docs-toolchain.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    outputs = sync.render_outputs(root)
    assert list(outputs) == [
        Path("website/requirements.txt"),
        Path("starter/docs-site/requirements.txt"),
        Path("aviato/library/scaffold/files/docs-requirements.txt.txt"),
    ]
    for rel_path, body in outputs.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body + "# drift\n", encoding="utf-8")

    assert sync.sync(root, check=True) == list(outputs)
    assert all((root / path).read_text(encoding="utf-8").endswith("# drift\n") for path in outputs)


def test_docs_pin_sync_rejects_floating_source_pin(tmp_path: Path) -> None:
    sync = _load_script("sync-docs-toolchain-pins.py")
    source = tmp_path / "aviato/library/docs-toolchain.yaml"
    source.parent.mkdir(parents=True)
    source.write_text(
        'zensical: ">=0.0.50"\n'
        'mike: "git+https://github.com/squidfunk/mike.git@2d4ad799442f4592db8ad53b179bfb33db8c69ac"\n'
        'pydoc-markdown: "4.8.2"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid exact pin"):
        sync.render_outputs(tmp_path)


def test_committed_docs_pin_outputs_are_current() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/sync-docs-toolchain-pins.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_regen_templates_check_lists_every_drift(tmp_path: Path) -> None:
    regen = _load_script("regen-templates.py")
    expected = regen.render_templates()
    root = tmp_path / "repo"
    for rel_path, body in expected.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body + "# drift\n", encoding="utf-8")

    assert regen.regenerate(root, check=True) == list(expected)
