from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from aviato.core.errors import PathConfinementError
from aviato.paths import REPO_ROOT


def _load_script(name: str) -> ModuleType:
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


def test_docs_pin_sync_declares_exactly_two_consumer_outputs_and_detects_all_drift(tmp_path: Path) -> None:
    sync = _load_script("sync-docs-toolchain-pins.py")
    root = tmp_path / "repo"
    (root / "aviato/library").mkdir(parents=True)
    (root / "aviato/library/docs-toolchain.yaml").write_text(
        (REPO_ROOT / "aviato/library/docs-toolchain.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    outputs = sync.render_outputs(root)
    assert list(outputs) == [
        Path("starter/docs-site/requirements.txt"),
        Path("aviato/library/scaffold/files/docs-requirements.txt.txt"),
    ]
    for rel_path, body in outputs.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body + "# drift\n", encoding="utf-8")

    assert sync.sync(root, check=True) == list(outputs)
    assert all((root / path).read_text(encoding="utf-8").endswith("# drift\n") for path in outputs)


def test_library_has_no_self_docs_site_but_consumer_docs_assets_remain() -> None:
    declaration = yaml.safe_load((REPO_ROOT / ".github/aviato.yaml").read_text(encoding="utf-8"))
    assert declaration["docs"] is False
    assert "serve-pages" not in declaration.get("variables", {})
    assert not (REPO_ROOT / "website").exists()
    assert not (REPO_ROOT / ".github/workflows/aviato-docs.yml").exists()
    assert not (REPO_ROOT / ".github/aviato.seed.json").exists()
    assert (REPO_ROOT / "starter/docs-site/docs.yml").is_file()
    assert (REPO_ROOT / "aviato/library/workflow-envelopes.yaml").is_file()
    assert (REPO_ROOT / "aviato/library/workflow-fragments/docs-python-library.yml").is_file()
    assert (REPO_ROOT / "aviato/library/workflow-fragments/docs-resolve.yml").is_file()


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
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "aviato/library", root / "aviato/library")
    (root / ".github").mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / ".github/aviato.yaml", root / ".github/aviato.yaml")
    expected = regen.render_templates(root)
    for rel_path, body in expected.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body + "# drift\n", encoding="utf-8")

    assert regen.regenerate(root, check=True) == list(expected)


@pytest.mark.parametrize("check", [False, True])
def test_docs_sync_rejects_symlink_source_without_touching_external_file(tmp_path: Path, check: bool) -> None:
    sync = _load_script("sync-docs-toolchain-pins.py")
    root = tmp_path / "repo"
    source = root / "aviato/library/docs-toolchain.yaml"
    source.parent.mkdir(parents=True)
    sentinel = tmp_path / "outside-source.yaml"
    sentinel.write_text("outside sentinel\n", encoding="utf-8")
    source.symlink_to(sentinel)

    with pytest.raises(PathConfinementError):
        sync.sync(root, check=check)

    assert sentinel.read_text(encoding="utf-8") == "outside sentinel\n"


@pytest.mark.parametrize("generator", ["sync", "regen"])
@pytest.mark.parametrize("check", [False, True])
def test_generators_reject_symlink_output_leaf(tmp_path: Path, generator: str, check: bool) -> None:
    sync = _load_script("sync-docs-toolchain-pins.py")
    regen = _load_script("regen-templates.py")
    root = tmp_path / "repo"
    if generator == "sync":
        source = root / "aviato/library/docs-toolchain.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(
            (REPO_ROOT / "aviato/library/docs-toolchain.yaml").read_text(encoding="utf-8"), encoding="utf-8"
        )
        outputs = sync.render_outputs(root)
    else:
        outputs = regen.render_templates()
    target = root / list(outputs)[-1]
    target.parent.mkdir(parents=True, exist_ok=True)
    sentinel = tmp_path / f"outside-{generator}.txt"
    sentinel.write_text("outside sentinel\n", encoding="utf-8")
    target.symlink_to(sentinel)

    with pytest.raises(PathConfinementError):
        if generator == "sync":
            sync.sync(root, check=check)
        else:
            regen.regenerate(root, check=check)

    assert sentinel.read_text(encoding="utf-8") == "outside sentinel\n"


@pytest.mark.parametrize("generator", ["sync", "regen"])
@pytest.mark.parametrize("check", [False, True])
def test_generators_reject_symlink_output_parent(tmp_path: Path, generator: str, check: bool) -> None:
    sync = _load_script("sync-docs-toolchain-pins.py")
    regen = _load_script("regen-templates.py")
    root = tmp_path / "repo"
    outside = tmp_path / f"outside-{generator}"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("outside sentinel\n", encoding="utf-8")
    if generator == "sync":
        source = root / "aviato/library/docs-toolchain.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(
            (REPO_ROOT / "aviato/library/docs-toolchain.yaml").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (root / "aviato/library/scaffold").symlink_to(outside, target_is_directory=True)
    else:
        root.mkdir(parents=True)
        (root / "templates").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathConfinementError):
        if generator == "sync":
            sync.sync(root, check=check)
        else:
            regen.regenerate(root, check=check)

    assert sentinel.read_text(encoding="utf-8") == "outside sentinel\n"


@pytest.mark.parametrize("generator", ["sync", "regen"])
def test_generator_preflights_all_outputs_before_mutating_any(tmp_path: Path, generator: str) -> None:
    sync = _load_script("sync-docs-toolchain-pins.py")
    regen = _load_script("regen-templates.py")
    root = tmp_path / "repo"
    if generator == "sync":
        source = root / "aviato/library/docs-toolchain.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(
            (REPO_ROOT / "aviato/library/docs-toolchain.yaml").read_text(encoding="utf-8"), encoding="utf-8"
        )
        outputs = sync.render_outputs(root)
    else:
        outputs = regen.render_templates()
    first = root / list(outputs)[0]
    first.parent.mkdir(parents=True, exist_ok=True)
    original = "earlier output must remain unchanged\n"
    first.write_text(original, encoding="utf-8")
    unsafe = root / list(outputs)[-1]
    unsafe.parent.mkdir(parents=True, exist_ok=True)
    sentinel = tmp_path / f"outside-atomic-{generator}.txt"
    sentinel.write_text("outside sentinel\n", encoding="utf-8")
    unsafe.symlink_to(sentinel)

    with pytest.raises(PathConfinementError):
        if generator == "sync":
            sync.sync(root)
        else:
            regen.regenerate(root)

    assert first.read_text(encoding="utf-8") == original
    assert sentinel.read_text(encoding="utf-8") == "outside sentinel\n"
