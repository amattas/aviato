from __future__ import annotations

import re
import shutil
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

import yaml

from . import github
from .command import run_to_path
from .core.errors import AviatoError
from .core.operation_context import LibrarySnapshot
from .core.ports import (
    GitObjectRead,
    GitObjectReadStatus,
    GitObjectType,
    GitRefNamespace,
    LibraryRefKind,
    RepositoryIdentity,
    ResolvedLibraryRef,
    validate_git_ref_name,
)
from .core.registry import Registry
from .policy import library_repository, load_policy

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_ANNOTATED_TAG_PEEL_DEPTH = 8


def configured_library_repository() -> str:
    """Return the pre-snapshot locator; fetched policy must corroborate it."""

    return library_repository(load_policy())


def _terminal_read_error(pin: str, read: GitObjectRead, *, operation: str) -> AviatoError:
    detail = read.error or "the endpoint returned no correlated object"
    return AviatoError(f"could not {operation} Library pin {pin!r}: {detail}")


def resolve_library_ref(repository: str, pin: str) -> ResolvedLibraryRef:
    """Resolve ``pin`` once, preferring tags, and return its immutable commit identity."""

    try:
        validate_git_ref_name(pin)
    except ValueError as exc:
        raise AviatoError(f"invalid Library pin ref {pin!r}: {exc}") from exc
    try:
        identity = github.repository_identity(repository)
    except (github.GitHubAPIError, ValueError) as exc:
        raise AviatoError(f"could not establish access to Library repository {repository}: {exc}") from exc

    access_probe = github.read_git_ref(identity, GitRefNamespace.HEADS, identity.default_branch)
    if (
        access_probe.status is not GitObjectReadStatus.FOUND
        or access_probe.object_type is not GitObjectType.COMMIT
        or access_probe.sha is None
    ):
        detail = access_probe.error or "the default branch was absent, malformed, or not a commit"
        raise AviatoError(
            f"could not establish Git content access through default branch {identity.default_branch!r} "
            f"in Library repository {identity.full_name}: {detail}"
        )

    resolved = github.read_git_ref(identity, GitRefNamespace.TAGS, pin)
    ref_kind = LibraryRefKind.TAG
    if resolved.status is GitObjectReadStatus.ERROR:
        raise _terminal_read_error(pin, resolved, operation="resolve tag for")
    if resolved.status is GitObjectReadStatus.NOT_FOUND:
        resolved = github.read_git_ref(identity, GitRefNamespace.HEADS, pin)
        ref_kind = LibraryRefKind.BRANCH
        if resolved.status is GitObjectReadStatus.ERROR:
            raise _terminal_read_error(pin, resolved, operation="resolve branch for")
    if resolved.status is GitObjectReadStatus.NOT_FOUND:
        raise AviatoError(f"Library pin {pin!r} does not resolve in {repository}; no archive was downloaded")
    if resolved.object_type is None or resolved.sha is None:
        raise AviatoError(f"Library pin {pin!r} produced an internally inconsistent Git object result")

    object_type = resolved.object_type
    object_sha = resolved.sha
    sha = object_sha
    if ref_kind is LibraryRefKind.BRANCH and object_type is not GitObjectType.COMMIT:
        raise AviatoError(f"Library branch {pin!r} resolved to invalid Git object type {object_type.value!r}")
    seen: set[str] = set()
    peel_depth = 0
    while object_type is GitObjectType.TAG:
        if sha in seen:
            raise AviatoError(f"annotated tag cycle while resolving Library pin {pin!r}")
        if peel_depth >= MAX_ANNOTATED_TAG_PEEL_DEPTH:
            raise AviatoError(
                f"annotated tag peel depth exceeds {MAX_ANNOTATED_TAG_PEEL_DEPTH} "
                f"while resolving Library pin {pin!r}"
            )
        seen.add(sha)
        peel_depth += 1
        peeled = github.read_annotated_tag(identity, sha)
        if peeled.status is not GitObjectReadStatus.FOUND:
            raise _terminal_read_error(pin, peeled, operation="peel annotated tag for")
        if peeled.object_type is None or peeled.sha is None:
            raise AviatoError(f"annotated Library tag {pin!r} produced an inconsistent Git object result")
        object_type, sha = peeled.object_type, peeled.sha
    if object_type is not GitObjectType.COMMIT or not _SHA_RE.fullmatch(sha):
        raise AviatoError(f"Library pin {pin!r} did not peel to a valid commit")
    return ResolvedLibraryRef(
        repository_identity=identity,
        ref_kind=ref_kind,
        requested_pin=pin,
        object_sha=object_sha,
        commit_sha=sha,
    )


def _resolve_commit(repository: str, pin: str) -> str:
    """Compatibility shim for internal callers while consumers migrate to OperationContext."""

    return resolve_library_ref(repository, pin).commit_sha


def _safe_library_members(
    archive: tarfile.TarFile,
    identity: RepositoryIdentity,
    sha: str,
) -> tuple[str, list[tarfile.TarInfo]]:
    members = archive.getmembers()
    if not members:
        raise AviatoError("downloaded Library archive is empty")
    roots: set[str] = set()
    selected: list[tarfile.TarInfo] = []
    for member in members:
        if "\\" in member.name:
            raise AviatoError(f"Library archive contains a backslash path, which is unsafe: {member.name!r}")
        path = PurePosixPath(member.name)
        if path.is_absolute() or member.name.startswith(("/", "\\")):
            raise AviatoError(f"Library archive contains an absolute path: {member.name!r}")
        if ".." in path.parts:
            raise AviatoError(f"Library archive contains an unsafe traversal path: {member.name!r}")
        if member.issym() or member.islnk():
            raise AviatoError(f"Library archive contains a link, which is not allowed: {member.name!r}")
        if not path.parts:
            continue
        roots.add(path.parts[0])
        if len(path.parts) >= 3 and path.parts[1:3] == ("aviato", "library"):
            if not (member.isfile() or member.isdir()):
                raise AviatoError(f"Library tree contains a non-regular archive entry: {member.name!r}")
            selected.append(member)
    if len(roots) != 1:
        raise AviatoError("Library archive does not have one commit-root directory")
    root = next(iter(roots))
    expected_root = f"{identity.full_name.replace('/', '-')}-{sha[:7]}"
    if root != expected_root:
        raise AviatoError(
            f"Library archive root {root!r} does not match repository {identity.full_name} "
            f"and resolved commit {sha}; expected {expected_root!r}"
        )
    if not any(m.isfile() and len(PurePosixPath(m.name).parts) > 3 for m in selected):
        raise AviatoError("Library archive is missing the aviato/library tree")
    return root, selected


def _contained_extraction_path(root: Path, relative: PurePosixPath) -> Path:
    """Resolve one archive destination and reject every escape from ``root``."""

    resolved_root = root.resolve(strict=True)
    resolved = root.joinpath(*relative.parts).resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise AviatoError(f"Library archive extraction target escapes the extraction root: {relative}") from exc
    return resolved


@contextmanager
def fetch_library_snapshot(repository: str, pin: str) -> Iterator[LibrarySnapshot]:
    """Yield one resolved, commit-addressed Library tree and its complete identity."""
    resolved = resolve_library_ref(repository, pin)
    sha = resolved.commit_sha
    workdir = Path(tempfile.mkdtemp(prefix="aviato-library-"))
    try:
        archive_path = workdir / "library.tar.gz"
        endpoint = f"repos/{resolved.repository_identity.full_name}/tarball/{sha}"
        result = run_to_path(["gh", "api", endpoint], archive_path, check=False)
        if result.returncode != 0:
            raise AviatoError(f"could not download Library archive for resolved commit {sha}: {result.stderr.strip()}")
        extract_root = workdir / "extracted"
        extract_root.mkdir()
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                archive_root, members = _safe_library_members(archive, resolved.repository_identity, sha)
                for member in members:
                    relative = PurePosixPath(member.name).relative_to(
                        PurePosixPath(archive_root) / "aviato" / "library"
                    )
                    if member.isdir():
                        destination = _contained_extraction_path(extract_root, relative)
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    parent = _contained_extraction_path(extract_root, relative.parent)
                    parent.mkdir(parents=True, exist_ok=True)
                    destination = _contained_extraction_path(extract_root, relative)
                    source = archive.extractfile(member)
                    if source is None:
                        raise AviatoError(f"could not read regular Library archive member {member.name!r}")
                    with source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)
        except (tarfile.TarError, OSError) as exc:
            raise AviatoError(f"could not safely extract Library archive: {exc}") from exc
        registry = Registry(extract_root)
        try:
            policy_repository = library_repository(load_policy(extract_root))
        except (AviatoError, OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
            raise AviatoError(f"fetched Library policy is invalid: {exc}") from exc
        if policy_repository.casefold() != resolved.repository_identity.full_name.casefold():
            raise AviatoError(
                f"fetched Library policy repository {policy_repository!r} does not match resolved "
                f"repository {resolved.repository_identity.full_name!r}"
            )
        snapshot = LibrarySnapshot(
            root=extract_root,
            registry=registry,
            policy_root=extract_root,
            requested_pin=pin,
            resolved_ref=resolved,
            _cleanup=lambda: shutil.rmtree(workdir, ignore_errors=True),
        )
        yield snapshot
    finally:
        if "snapshot" in locals():
            snapshot.close()
        else:
            shutil.rmtree(workdir, ignore_errors=True)


@contextmanager
def fetch_library_registry(repository: str, pin: str) -> Iterator[Registry]:
    """Compatibility adapter over :func:`fetch_library_snapshot`; never resolves twice."""

    with fetch_library_snapshot(repository, pin) as snapshot:
        yield snapshot.registry
