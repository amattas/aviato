from __future__ import annotations

import json
import re
import shutil
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .command import run
from .core.errors import AviatoError
from .core.registry import Registry

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _read_object(repository: str, endpoint: str) -> tuple[str, str] | None:
    result = run(["gh", "api", f"repos/{repository}/{endpoint}"], check=False)
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
        obj = payload["object"]
        object_type, sha = obj["type"], obj["sha"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AviatoError(f"could not parse resolved Library ref from GitHub: {exc}") from exc
    if object_type not in ("commit", "tag") or not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
        raise AviatoError(f"Library ref resolved to an invalid Git object: type={object_type!r}, sha={sha!r}")
    return object_type, sha


def _resolve_commit(repository: str, pin: str) -> str:
    encoded = quote(pin, safe="")
    resolved = _read_object(repository, f"git/ref/tags/{encoded}")
    if resolved is None:
        resolved = _read_object(repository, f"git/ref/heads/{encoded}")
    if resolved is None:
        raise AviatoError(f"Library pin {pin!r} does not resolve in {repository}; no archive was downloaded")
    object_type, sha = resolved
    seen: set[str] = set()
    while object_type == "tag":
        if sha in seen:
            raise AviatoError(f"annotated tag cycle while resolving Library pin {pin!r}")
        seen.add(sha)
        peeled = _read_object(repository, f"git/tags/{sha}")
        if peeled is None:
            raise AviatoError(f"could not peel annotated Library tag {pin!r}")
        object_type, sha = peeled
    return sha


def _safe_library_members(archive: tarfile.TarFile, sha: str) -> tuple[str, list[tarfile.TarInfo]]:
    members = archive.getmembers()
    if not members:
        raise AviatoError("downloaded Library archive is empty")
    roots: set[str] = set()
    selected: list[tarfile.TarInfo] = []
    for member in members:
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
    if sha[:7] not in root:
        raise AviatoError(f"Library archive commit root {root!r} does not match resolved commit {sha}")
    if not any(m.isfile() and len(PurePosixPath(m.name).parts) > 3 for m in selected):
        raise AviatoError("Library archive is missing the aviato/library tree")
    return root, selected


@contextmanager
def fetch_library_registry(repository: str, pin: str) -> Iterator[Registry]:
    """Yield the exact published Library registry for ``pin``, then remove all fetched bytes."""
    sha = _resolve_commit(repository, pin)
    workdir = Path(tempfile.mkdtemp(prefix="aviato-library-"))
    try:
        archive_path = workdir / "library.tar.gz"
        result = run(["gh", "api", f"repos/{repository}/tarball/{sha}", "--output", str(archive_path)], check=False)
        if result.returncode != 0:
            raise AviatoError(f"could not download Library archive for resolved commit {sha}: {result.stderr.strip()}")
        extract_root = workdir / "extracted"
        extract_root.mkdir()
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                archive_root, members = _safe_library_members(archive, sha)
                for member in members:
                    relative = PurePosixPath(member.name).relative_to(
                        PurePosixPath(archive_root) / "aviato" / "library"
                    )
                    destination = extract_root.joinpath(*relative.parts)
                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise AviatoError(f"could not read regular Library archive member {member.name!r}")
                    with source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)
        except (tarfile.TarError, OSError) as exc:
            raise AviatoError(f"could not safely extract Library archive: {exc}") from exc
        yield Registry(extract_root)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
