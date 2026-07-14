from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

from aviato.core.declaration import Declaration
from aviato.core.errors import AviatoError


def _operation_context():
    return importlib.import_module("aviato.core.operation_context")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _library_checkout(root: Path) -> None:
    (root / "aviato/core").mkdir(parents=True)
    (root / "aviato/core/__init__.py").write_text("", encoding="utf-8")
    (root / "aviato/library/bundles").mkdir(parents=True)
    (root / "aviato/library/scaffold").mkdir(parents=True)
    (root / "aviato/library/policy.yml").write_text(
        "library:\n  repository: owner/library\nrelease: {}\n", encoding="utf-8"
    )
    (root / "aviato/library/profile.yaml").write_text(
        "name: profile\nidentity: profile/v1\nworkflows: wf\nscaffold: sc\nsettings: set\n",
        encoding="utf-8",
    )
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")


def _bootstrap() -> Declaration:
    return Declaration(profile="profile", version="0", bootstrap=True)


def test_operation_context_owns_registry_policy_root_and_archive_lifetime(tmp_path: Path) -> None:
    _library_checkout(tmp_path)

    with _operation_context().bootstrap_operation_context(tmp_path, _bootstrap(), tool_version="1.2.3") as context:
        snapshot_root = context.snapshot.root
        assert context.registry.root == snapshot_root
        assert context.policy_root == snapshot_root
        assert context.target_root == tmp_path.resolve()
        assert context.tool_version == "1.2.3"
        assert snapshot_root.is_dir()

    assert not snapshot_root.exists()


def test_operation_context_canonicalizes_the_target_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _library_checkout(tmp_path)
    module = _operation_context()
    original = module.canonical_repository_root
    calls: list[Path] = []

    def counted(target: Path) -> Path:
        calls.append(target)
        return original(target)

    monkeypatch.setattr(module, "canonical_repository_root", counted)

    with module.operation_context(
        tmp_path,
        _bootstrap(),
        repository="owner/library",
        tool_version="1.2.3",
    ):
        pass

    assert calls == [tmp_path]


def test_canonical_dot_tmp_alias_and_symlink_targets_resolve_before_any_write(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)

    assert _operation_context().canonical_repository_root(alias) == repo.resolve()
    assert _operation_context().canonical_repository_root(repo / ".") == repo.resolve()


def test_nested_repository_directory_and_non_repository_target_are_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "nested"
    nested.mkdir(parents=True)
    _git(repo, "init")

    with pytest.raises(AviatoError, match="repository root"):
        _operation_context().canonical_repository_root(nested)
    (tmp_path / "elsewhere").mkdir()
    with pytest.raises(AviatoError, match="not a Git repository"):
        _operation_context().canonical_repository_root(tmp_path / "elsewhere")
    with pytest.raises(AviatoError, match="does not exist"):
        _operation_context().canonical_repository_root(tmp_path / "missing")


def test_bootstrap_snapshot_reads_operated_checkout_not_installed_package(tmp_path: Path) -> None:
    _library_checkout(tmp_path)
    operated = (tmp_path / "aviato/library/profile.yaml").read_text(encoding="utf-8")

    with _operation_context().bootstrap_operation_context(tmp_path, _bootstrap(), tool_version="1.0.0") as context:
        assert context.registry.profile_doc("profile")["identity"] == "profile/v1"
        assert (context.snapshot.root / "profile.yaml").read_text(encoding="utf-8") == operated


def test_bootstrap_snapshot_records_head_and_deterministic_library_tree_digest(tmp_path: Path) -> None:
    _library_checkout(tmp_path)
    head = _git(tmp_path, "rev-parse", "HEAD")

    with _operation_context().bootstrap_operation_context(tmp_path, _bootstrap(), tool_version="1.0.0") as first:
        first_digest = first.snapshot.tree_digest
        assert first.snapshot.local_head == head
    with _operation_context().bootstrap_operation_context(tmp_path, _bootstrap(), tool_version="1.0.0") as second:
        assert second.snapshot.tree_digest == first_digest


def test_tree_digest_domain_separates_empty_file_and_empty_directory(tmp_path: Path) -> None:
    file_tree = tmp_path / "file-tree"
    directory_tree = tmp_path / "directory-tree"
    file_tree.mkdir()
    directory_tree.mkdir()
    (file_tree / "entry").touch()
    (directory_tree / "entry").mkdir()

    file_digest = _operation_context()._tree_digest(file_tree)
    directory_digest = _operation_context()._tree_digest(directory_tree)

    assert file_digest != directory_digest
    assert _operation_context()._tree_digest(file_tree) == file_digest
    assert _operation_context()._tree_digest(directory_tree) == directory_digest


def test_bootstrap_snapshot_copies_then_hashes_the_same_immutable_tree(tmp_path: Path) -> None:
    _library_checkout(tmp_path)

    with _operation_context().bootstrap_operation_context(tmp_path, _bootstrap(), tool_version="1.0.0") as context:
        copied = context.snapshot.root / "profile.yaml"
        before = copied.read_bytes()
        (tmp_path / "aviato/library/profile.yaml").write_text("identity: mutated\n", encoding="utf-8")
        assert copied.read_bytes() == before
        assert context.snapshot.tree_digest is not None


def test_bootstrap_is_rejected_outside_a_structural_library_before_render(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    with (
        pytest.raises(AviatoError, match="structurally verified"),
        _operation_context().bootstrap_operation_context(tmp_path, _bootstrap(), tool_version="1.0.0"),
    ):
        pass


def test_symlinked_bootstrap_structure_is_rejected(tmp_path: Path) -> None:
    _library_checkout(tmp_path)
    real = tmp_path / "real-bundles"
    real.mkdir()
    (tmp_path / "aviato/library/bundles").rmdir()
    (tmp_path / "aviato/library/bundles").symlink_to(real, target_is_directory=True)

    with (
        pytest.raises(AviatoError, match="symlink"),
        _operation_context().bootstrap_operation_context(tmp_path, _bootstrap(), tool_version="1.0.0"),
    ):
        pass


def test_bootstrap_snapshot_rejects_non_anchor_symlinks(tmp_path: Path) -> None:
    _library_checkout(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside Library tree\n", encoding="utf-8")
    (tmp_path / "aviato/library/linked.txt").symlink_to(outside)

    with (
        pytest.raises(AviatoError, match="snapshot contains a symlink"),
        _operation_context().bootstrap_operation_context(tmp_path, _bootstrap(), tool_version="1.0.0"),
    ):
        pass
