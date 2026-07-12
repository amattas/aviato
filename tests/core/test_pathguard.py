from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aviato.core.declaration import Declaration, dump_declaration
from aviato.core.errors import PathConfinementError
from aviato.core.pathguard import confined_target
from aviato.core.scaffold import read_sidecar

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_path_confinement_api_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathConfinementError, match=r"write.*\.\./outside\.txt"):
        confined_target(tmp_path, "../outside.txt", operation="write")


@pytest.mark.parametrize("relative", ["", ".", "/tmp/outside", r"\outside", r"C:\outside"])
def test_path_confinement_rejects_non_relative_targets(tmp_path: Path, relative: str) -> None:
    with pytest.raises(PathConfinementError, match="inspect"):
        confined_target(tmp_path, relative, operation="inspect")


def test_path_confinement_rejects_existing_symlink_leaf(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (tmp_path / "leaf.txt").symlink_to(outside)

    with pytest.raises(PathConfinementError, match="leaf.txt"):
        confined_target(tmp_path, "leaf.txt", operation="read")


def test_dump_declaration_rejects_symlinked_leaf(tmp_path: Path) -> None:
    github = tmp_path / ".github"
    github.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-declaration.yaml"
    original = b"profile: outside\nversion: '1'\n"
    outside.write_bytes(original)
    (github / "aviato.yaml").symlink_to(outside)

    with pytest.raises(PathConfinementError, match=r"write declaration.*\.github/aviato\.yaml"):
        dump_declaration(Declaration(profile="p", version="1"), tmp_path, ".github/aviato.yaml")

    assert outside.read_bytes() == original


def test_read_sidecar_rejects_symlinked_leaf(tmp_path: Path) -> None:
    github = tmp_path / ".github"
    github.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-seed.json"
    original = b'{"outside": "unchanged"}\n'
    outside.write_bytes(original)
    (github / "aviato.seed.json").symlink_to(outside)

    with pytest.raises(PathConfinementError, match=r"read sidecar.*\.github/aviato\.seed\.json"):
        read_sidecar(tmp_path)

    assert outside.read_bytes() == original


def test_registry_rejects_symlinked_module_definition(tmp_path: Path) -> None:
    from aviato.core.registry import Registry

    outside = tmp_path.parent / f"{tmp_path.name}-profile.yaml"
    outside.write_text("name: p\nworkflows: w\nscaffold: s\nsettings: x\n", encoding="utf-8")
    (tmp_path / "p.yaml").symlink_to(outside)

    with pytest.raises(PathConfinementError, match=r"read module definition.*p\.yaml"):
        Registry(tmp_path).profile("p")


def test_registry_rejects_symlinked_template_source(tmp_path: Path) -> None:
    from aviato.core.model import TemplateModule
    from aviato.core.registry import Registry

    scaffold_root = tmp_path / "scaffold"
    scaffold_root.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-template.txt"
    original = b"outside template\n"
    outside.write_bytes(original)
    (scaffold_root / "body.txt").symlink_to(outside)
    module = TemplateModule(output_path="cfg.txt", source="body.txt")

    with pytest.raises(PathConfinementError, match=r"read template source.*scaffold/body\.txt"):
        Registry(tmp_path).template_body(module)

    assert outside.read_bytes() == original


def test_consumer_and_module_boundaries_do_not_reintroduce_direct_joins() -> None:
    guarded_modules = {
        "aviato/core/scaffold.py": ("root / output",),
        "aviato/core/diagnosis.py": ("root / artifact.output_path", "root / candidate"),
        "aviato/core/offboarding.py": ("root / output",),
        "aviato/core/registry.py": ("self.root /",),
        "aviato/github_platform.py": ("self.workdir / output_path",),
        "aviato/plugins/version_formats.py": ("Path(root) / location",),
        "aviato/cli.py": (
            "root / artifact.output_path",
            "clone / artifact.output",
            "root / loc",
        ),
    }
    for relative_file, forbidden in guarded_modules.items():
        tree = ast.parse((REPO_ROOT / relative_file).read_text(encoding="utf-8"))
        direct_joins = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.BinOp)]
        for expression in forbidden:
            path_join_is_guarded = all(expression not in direct_join for direct_join in direct_joins)
            assert path_join_is_guarded, f"{relative_file} reintroduced unguarded path join {expression!r}"

    declaration_tree = ast.parse((REPO_ROOT / "aviato/core/declaration.py").read_text(encoding="utf-8"))
    declaration_calls = [node for node in ast.walk(declaration_tree) if isinstance(node, ast.Call)]
    assert not any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "write_text" for call in declaration_calls
    )

    cli_tree = ast.parse((REPO_ROOT / "aviato/cli.py").read_text(encoding="utf-8"))
    load_calls = [
        call
        for call in ast.walk(cli_tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "load_declaration"
    ]
    assert len(load_calls) == 1
    assert "_consumer_declaration_target" in ast.unparse(load_calls[0])
    dump_calls = [
        call
        for call in ast.walk(cli_tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "dump_declaration"
    ]
    assert len(dump_calls) == 1
    assert ast.unparse(dump_calls[0]).endswith("DECLARATION_RELATIVE_PATH)")
