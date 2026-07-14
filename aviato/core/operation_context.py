from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from ..command import run
from .bootstrap import is_library, structural_anchors
from .declaration import Declaration
from .errors import AviatoError
from .ports import RepositoryIdentity, ResolvedLibraryRef
from .registry import Registry


@dataclass(frozen=True)
class LibrarySnapshot:
    """One immutable Library tree and the identity that selected its bytes."""

    root: Path
    registry: Registry
    policy_root: Path
    requested_pin: str
    resolved_ref: ResolvedLibraryRef | None = None
    local_head: str | None = None
    tree_digest: str | None = None
    _cleanup: Callable[[], None] = field(default=lambda: None, repr=False, compare=False)

    @property
    def resolved_ref_kind(self) -> str:
        return "bootstrap" if self.resolved_ref is None else self.resolved_ref.ref_kind.value

    @property
    def commit_sha(self) -> str:
        return self.local_head or (self.resolved_ref.commit_sha if self.resolved_ref is not None else "")

    @property
    def repository_identity(self) -> RepositoryIdentity | None:
        return None if self.resolved_ref is None else self.resolved_ref.repository_identity

    def close(self) -> None:
        self._cleanup()


@dataclass(frozen=True)
class OperationContext:
    """All authority and immutable data for one repository operation."""

    target_root: Path
    declaration: Declaration | None
    snapshot: LibrarySnapshot
    tool_version: str

    @property
    def registry(self) -> Registry:
        return self.snapshot.registry

    @property
    def policy_root(self) -> Path:
        return self.snapshot.policy_root


def canonical_repository_root(target: Path) -> Path:
    """Return an operated Git root, rejecting aliases to nested/non-repository paths."""

    supplied = Path(target)
    if not supplied.exists():
        raise AviatoError(f"repository target does not exist: {supplied}")
    if not supplied.is_dir():
        raise AviatoError(f"repository target is not a directory: {supplied}")
    canonical = supplied.resolve(strict=True)
    result = run(["git", "-C", str(canonical), "rev-parse", "--show-toplevel"], check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise AviatoError(f"target is not a Git repository: {supplied}")
    root = Path(result.stdout.strip()).resolve(strict=True)
    if canonical != root:
        raise AviatoError(f"target must be the repository root {root}, not nested path {canonical}")
    return root


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise AviatoError(f"bootstrap Library snapshot contains a symlink: {relative}")
        relative_bytes = relative.encode("utf-8")
        digest.update(b"entry\0")
        digest.update(str(len(relative_bytes)).encode("ascii"))
        digest.update(b"\0")
        digest.update(relative_bytes)
        digest.update(b"\0")
        if path.is_dir():
            digest.update(b"directory\0")
        elif path.is_file():
            body = path.read_bytes()
            digest.update(b"file\0")
            digest.update(str(len(body)).encode("ascii"))
            digest.update(b"\0")
            digest.update(body)
            digest.update(b"\0")
        else:
            raise AviatoError(f"bootstrap Library snapshot contains an unsupported entry: {relative}")
    return digest.hexdigest()


def _verify_bootstrap_structure(root: Path, declaration: Declaration) -> None:
    if not declaration.bootstrap:
        raise AviatoError("bootstrap operation requires bootstrap: true in the operated declaration")
    if not is_library(root):
        raise AviatoError("bootstrap is valid only in a structurally verified Library checkout")
    for anchor in structural_anchors(root):
        current = root
        for part in anchor.relative_to(root).parts:
            current /= part
            if current.is_symlink():
                raise AviatoError(f"bootstrap structural anchor must not be a symlink: {current}")


@contextmanager
def _bootstrap_operation_context_for_root(
    root: Path,
    declaration: Declaration,
    *,
    tool_version: str,
) -> Iterator[OperationContext]:
    """Build a bootstrap context for a root already selected by the caller."""

    _verify_bootstrap_structure(root, declaration)
    workdir = Path(tempfile.mkdtemp(prefix="aviato-bootstrap-"))
    snapshot_root = workdir / "library"
    try:
        shutil.copytree(root / "aviato" / "library", snapshot_root, symlinks=True)
        digest = _tree_digest(snapshot_root)
        head_result = run(["git", "-C", str(root), "rev-parse", "HEAD"], check=False)
        if head_result.returncode != 0 or not head_result.stdout.strip():
            raise AviatoError("could not record bootstrap Library Git HEAD")
        snapshot = LibrarySnapshot(
            root=snapshot_root,
            registry=Registry(snapshot_root),
            policy_root=snapshot_root,
            requested_pin=declaration.version,
            local_head=head_result.stdout.strip(),
            tree_digest=digest,
            _cleanup=lambda: shutil.rmtree(workdir, ignore_errors=True),
        )
        yield OperationContext(root, declaration, snapshot, tool_version)
    finally:
        if "snapshot" in locals():
            snapshot.close()
        else:
            shutil.rmtree(workdir, ignore_errors=True)


@contextmanager
def bootstrap_operation_context(
    target: Path,
    declaration: Declaration,
    *,
    tool_version: str,
) -> Iterator[OperationContext]:
    """Canonicalize once, then copy and identify the checkout-local Library tree."""

    root = canonical_repository_root(target)
    with _bootstrap_operation_context_for_root(root, declaration, tool_version=tool_version) as context:
        yield context


@contextmanager
def _published_operation_context_for_root(
    root: Path,
    declaration: Declaration | None,
    *,
    repository: str,
    pin: str,
    tool_version: str,
) -> Iterator[OperationContext]:
    """Build a published context for a root already selected by the caller."""

    from ..library_source import fetch_library_snapshot

    with fetch_library_snapshot(repository, pin) as snapshot:
        yield OperationContext(root, declaration, snapshot, tool_version)


@contextmanager
def published_operation_context(
    target: Path,
    declaration: Declaration | None,
    *,
    repository: str,
    pin: str,
    tool_version: str,
) -> Iterator[OperationContext]:
    """Canonicalize once, then open one commit-addressed published snapshot."""

    root = canonical_repository_root(target)
    with _published_operation_context_for_root(
        root,
        declaration,
        repository=repository,
        pin=pin,
        tool_version=tool_version,
    ) as context:
        yield context


@contextmanager
def operation_context_for_root(
    root: Path,
    declaration: Declaration | None,
    *,
    repository: str,
    pin: str | None = None,
    tool_version: str,
) -> Iterator[OperationContext]:
    """Open a context after the command has selected its canonical repository root."""

    if declaration is not None and declaration.bootstrap:
        with _bootstrap_operation_context_for_root(root, declaration, tool_version=tool_version) as context:
            yield context
        return
    selected_pin = pin or (declaration.version if declaration is not None else None)
    if selected_pin is None:
        raise AviatoError("this consumer operation requires an explicit Library pin or declaration context")
    with _published_operation_context_for_root(
        root,
        declaration,
        repository=repository,
        pin=selected_pin,
        tool_version=tool_version,
    ) as context:
        yield context


@contextmanager
def operation_context(
    target: Path,
    declaration: Declaration | None,
    *,
    repository: str,
    pin: str | None = None,
    tool_version: str,
) -> Iterator[OperationContext]:
    """Canonicalize once, then choose bootstrap or one published snapshot."""

    root = canonical_repository_root(target)
    with operation_context_for_root(
        root,
        declaration,
        repository=repository,
        pin=pin,
        tool_version=tool_version,
    ) as context:
        yield context
