from __future__ import annotations

import base64
import errno
import fcntl
import hashlib
import json
import os
import stat
import unicodedata
import uuid
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal, cast

from aviato.command import CommandError, run_bytes

from .errors import AviatoError
from .outcomes import OperationResult, OperationStatus, TransitionResult

if TYPE_CHECKING:
    from .inventory import ManagedInventory

OperationCategory = Literal["managed", "seed", "sidecar", "declaration", "inventory"]
FingerprintKind = Literal["missing", "file", "unsafe"]
FaultHook = Callable[[str, "TransitionOperation | None"], None]
Validator = Callable[[Path, "TransitionPlan"], bool]

_CATEGORY_ORDER: dict[str, int] = {
    "managed": 0,
    "seed": 1,
    "sidecar": 2,
    "declaration": 3,
    "inventory": 4,
}
_STATE_SCHEMA = 1


class TransitionError(AviatoError):
    """A repository transition could not be planned or executed safely."""


class TransitionConflictError(TransitionError):
    """Preconditions changed or planning found a blocking repository conflict."""


class TransitionRecoveryError(TransitionError):
    """A pending transition requires explicit, safe recovery."""


class TransitionExecutionError(TransitionError):
    def __init__(self, message: str, result: TransitionResult) -> None:
        self.result = result
        super().__init__(message)


@dataclass(frozen=True)
class FileFingerprint:
    kind: FingerprintKind
    sha256: str | None = None
    mode: int | None = None
    size: int | None = None


@dataclass(frozen=True)
class TransitionChange:
    path: str
    category: OperationCategory
    desired_bytes: bytes | None
    mode: int | None = None

    @classmethod
    def write(
        cls,
        path: str,
        desired_bytes: bytes,
        *,
        category: OperationCategory,
        mode: int | None = None,
    ) -> TransitionChange:
        return cls(path=path, category=category, desired_bytes=bytes(desired_bytes), mode=mode)

    @classmethod
    def delete(cls, path: str, *, category: OperationCategory) -> TransitionChange:
        return cls(path=path, category=category, desired_bytes=None)


@dataclass(frozen=True)
class TransitionOperation:
    operation_id: str
    kind: Literal["replace", "delete"]
    path: str
    category: OperationCategory
    desired_bytes: bytes | None
    mode: int | None
    expected: FileFingerprint

    @property
    def desired(self) -> FileFingerprint:
        if self.kind == "delete":
            return FileFingerprint("missing")
        assert self.desired_bytes is not None
        return FileFingerprint(
            "file",
            hashlib.sha256(self.desired_bytes).hexdigest(),
            self.mode,
            len(self.desired_bytes),
        )


@dataclass(frozen=True)
class TransitionPlan:
    canonical_root: Path
    snapshot_sha: str
    declaration_identity: str
    operations: tuple[TransitionOperation, ...]
    conflicts: tuple[str, ...]
    notices: tuple[str, ...]
    validation_exclusions: tuple[str, ...]
    digest: str


@dataclass(frozen=True)
class TransitionInspection:
    pending: bool
    journal_id: str = ""
    plan_digest: str = ""
    operations: tuple[OperationResult, ...] = ()


@dataclass(frozen=True)
class PlannedRepositoryTransition:
    plan: TransitionPlan
    written: tuple[str, ...] = ()
    seeded: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    preserved_seeds: tuple[str, ...] = ()
    baselined: tuple[str, ...] = ()
    retired: tuple[str, ...] = ()


@dataclass(frozen=True)
class _TransitionState:
    path: Path
    state_fd: int
    journals_fd: int


@dataclass(frozen=True)
class _JournalRef:
    state: _TransitionState
    name: str


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _unique_json(payload: bytes, *, context: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise TransitionRecoveryError(f"{context} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(payload, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransitionRecoveryError(f"{context} is not valid JSON") from exc


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write while persisting transition state")
        view = view[written:]


def _read_regular_nofollow(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise FileNotFoundError(path) from exc
        raise TransitionRecoveryError(f"could not securely open transition state {path.name}: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise TransitionRecoveryError(f"transition state {path.name} is not a regular file")
        chunks: list[bytes] = []
        while block := os.read(fd, 1024 * 1024):
            chunks.append(block)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _fingerprint_data(value: FileFingerprint) -> dict[str, object]:
    return {"kind": value.kind, "sha256": value.sha256, "mode": value.mode, "size": value.size}


def _fingerprint_from_data(value: object) -> FileFingerprint:
    if not isinstance(value, dict) or set(value) != {"kind", "sha256", "mode", "size"}:
        raise TransitionRecoveryError("transition journal contains an invalid fingerprint")
    kind = value["kind"]
    if kind not in {"missing", "file", "unsafe"}:
        raise TransitionRecoveryError("transition journal contains an invalid fingerprint kind")
    sha256 = value["sha256"]
    mode = value["mode"]
    size = value["size"]
    if sha256 is not None and (not isinstance(sha256, str) or len(sha256) != 64):
        raise TransitionRecoveryError("transition journal contains an invalid fingerprint hash")
    if mode is not None and type(mode) is not int:
        raise TransitionRecoveryError("transition journal contains an invalid fingerprint mode")
    if size is not None and type(size) is not int:
        raise TransitionRecoveryError("transition journal contains an invalid fingerprint size")
    return FileFingerprint(kind, sha256, mode, size)


def _validate_relative(path: str) -> str:
    if not isinstance(path, str) or not path or "\0" in path or "\\" in path:
        raise TransitionConflictError(f"unsafe transition path {path!r}")
    pure = PurePosixPath(path)
    if pure.is_absolute() or pure.as_posix() != path or any(part in {"", ".", ".."} for part in pure.parts):
        raise TransitionConflictError(f"unsafe transition path {path!r}")
    folded = tuple(part.casefold() for part in pure.parts)
    if ".git" in folded or ".worktrees" in folded:
        raise TransitionConflictError(f"transition path targets protected Git metadata: {path!r}")
    return path


def _path_identity(path: str) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", component).casefold() for component in PurePosixPath(path).parts)


def _single_git_path(root: Path, *arguments: str) -> Path:
    try:
        result = run_bytes(["git", "-C", str(root), *arguments])
    except CommandError as exc:
        raise TransitionConflictError(f"could not resolve repository metadata: {exc}") from exc
    raw = result.stdout
    if not raw.endswith(b"\n") or b"\0" in raw:
        raise TransitionConflictError("Git returned malformed repository metadata")
    return Path(os.fsdecode(raw[:-1]))


def _canonical_repo(root: Path) -> Path:
    requested = root.resolve()
    actual = _single_git_path(requested, "rev-parse", "--path-format=absolute", "--show-toplevel").resolve()
    if requested != actual:
        raise TransitionConflictError(f"repository root must be canonical: requested {requested}, actual {actual}")
    return actual


def _pathname_fingerprint(root: Path, relative: str) -> FileFingerprint:
    current = root
    parts = PurePosixPath(relative).parts
    for part in parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return FileFingerprint("missing")
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            return FileFingerprint("unsafe")
    path = root / relative
    try:
        info = path.lstat()
    except FileNotFoundError:
        return FileFingerprint("missing")
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return FileFingerprint("unsafe")
    try:
        payload = path.read_bytes()
    except OSError:
        return FileFingerprint("unsafe")
    return FileFingerprint("file", hashlib.sha256(payload).hexdigest(), stat.S_IMODE(info.st_mode), len(payload))


def _dirty_paths(root: Path) -> tuple[str, ...]:
    try:
        result = run_bytes(["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"])
    except CommandError as exc:
        raise TransitionConflictError(f"could not inspect working tree: {exc}") from exc
    records = result.stdout.split(b"\0")
    if records and records[-1] == b"":
        records.pop()
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        if len(record) < 4 or record[2:3] != b" ":
            raise TransitionConflictError("Git returned malformed NUL-delimited status output")
        paths.append(os.fsdecode(record[3:]))
        if record[:1] in {b"R", b"C"} or record[1:2] in {b"R", b"C"}:
            index += 1
            if index >= len(records):
                raise TransitionConflictError("Git returned a truncated rename status")
            paths.append(os.fsdecode(records[index]))
        index += 1
    return tuple(paths)


def _operation_data(operation: TransitionOperation) -> dict[str, object]:
    return {
        "operation_id": operation.operation_id,
        "kind": operation.kind,
        "path": operation.path,
        "category": operation.category,
        "desired_bytes": (
            base64.b64encode(operation.desired_bytes).decode("ascii") if operation.desired_bytes is not None else None
        ),
        "mode": operation.mode,
        "expected": _fingerprint_data(operation.expected),
    }


def _validate_plan(plan: TransitionPlan) -> None:
    if _canonical_repo(plan.canonical_root) != plan.canonical_root:
        raise TransitionConflictError("transition plan root is no longer canonical")
    ordered = sorted(
        plan.operations,
        key=lambda item: (_CATEGORY_ORDER.get(item.category, 99), _path_identity(item.path), item.path),
    )
    if list(plan.operations) != ordered:
        raise TransitionConflictError("transition plan operations are not in deterministic order")
    identities: set[tuple[str, ...]] = set()
    for index, operation in enumerate(plan.operations, 1):
        if operation.operation_id != f"op-{index:04d}":
            raise TransitionConflictError("transition plan operation IDs are not canonical")
        _validate_relative(operation.path)
        identity = _path_identity(operation.path)
        if identity in identities:
            raise TransitionConflictError("transition plan contains duplicate path identities")
        identities.add(identity)
        if operation.category not in _CATEGORY_ORDER:
            raise TransitionConflictError("transition plan contains an unknown operation category")
        if operation.kind == "replace":
            if operation.desired_bytes is None or operation.mode is None:
                raise TransitionConflictError("replacement operation is missing desired bytes or mode")
        elif operation.kind == "delete":
            if operation.desired_bytes is not None or operation.mode is not None:
                raise TransitionConflictError("deletion operation carries replacement data")
        else:
            raise TransitionConflictError("transition plan contains an unknown operation kind")
        if operation.expected.kind == "unsafe":
            raise TransitionConflictError("transition plan contains an unsafe preimage")
    canonical_exclusions = tuple(sorted({_validate_relative(path) for path in plan.validation_exclusions}))
    if canonical_exclusions != plan.validation_exclusions:
        raise TransitionConflictError("transition validation exclusions are not canonical")
    payload = _plan_payload(
        plan.canonical_root,
        plan.snapshot_sha,
        plan.declaration_identity,
        plan.operations,
        plan.conflicts,
        plan.notices,
        plan.validation_exclusions,
    )
    expected_digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    if plan.digest != expected_digest:
        raise TransitionConflictError("transition plan digest does not match its canonical payload")


def _plan_payload(
    root: Path,
    snapshot_sha: str,
    declaration_identity: str,
    operations: Sequence[TransitionOperation],
    conflicts: Sequence[str],
    notices: Sequence[str],
    validation_exclusions: Sequence[str],
) -> dict[str, object]:
    return {
        "canonical_root": str(root),
        "snapshot_sha": snapshot_sha,
        "declaration_identity": declaration_identity,
        "operations": [_operation_data(operation) for operation in operations],
        "conflicts": list(conflicts),
        "notices": list(notices),
        "validation_exclusions": list(validation_exclusions),
    }


def build_transition_plan(
    root: Path,
    *,
    snapshot_sha: str,
    declaration_identity: str,
    changes: Iterable[TransitionChange],
    conflicts: Iterable[str] = (),
    notices: Iterable[str] = (),
    validation_exclusions: Iterable[str] = (),
    allow_dirty: bool = False,
) -> TransitionPlan:
    canonical = _canonical_repo(Path(root))
    if not snapshot_sha or not declaration_identity:
        raise TransitionConflictError("snapshot SHA and declaration identity are required")
    by_identity: dict[tuple[str, ...], TransitionChange] = {}
    planning_conflicts = list(conflicts)
    for change in changes:
        path = _validate_relative(change.path)
        identity = _path_identity(path)
        if change.category not in _CATEGORY_ORDER:
            raise TransitionConflictError(f"unknown operation category {change.category!r}")
        if identity in by_identity:
            planning_conflicts.append(f"duplicate or case-equivalent planned path: {path}")
            continue
        if change.mode is not None and not 0 <= change.mode <= 0o7777:
            planning_conflicts.append(f"invalid mode for {path}: {change.mode!r}")
        by_identity[identity] = change

    operations: list[TransitionOperation] = []
    for change in sorted(
        by_identity.values(), key=lambda item: (_CATEGORY_ORDER[item.category], _path_identity(item.path), item.path)
    ):
        expected = _pathname_fingerprint(canonical, change.path)
        if expected.kind == "unsafe":
            planning_conflicts.append(f"planned path is not a confined regular file or absence: {change.path}")
        mode = None
        kind: Literal["replace", "delete"]
        if change.desired_bytes is None:
            kind = "delete"
        else:
            kind = "replace"
            mode = change.mode if change.mode is not None else (expected.mode if expected.kind == "file" else 0o644)
        operations.append(
            TransitionOperation(
                operation_id=f"op-{len(operations) + 1:04d}",
                kind=kind,
                path=change.path,
                category=change.category,
                desired_bytes=change.desired_bytes,
                mode=mode,
                expected=expected,
            )
        )

    dirty = _dirty_paths(canonical)
    planned = {_path_identity(operation.path) for operation in operations}
    overlap = sorted(path for path in dirty if _path_identity(path) in planned)
    if overlap:
        planning_conflicts.extend(f"dirty worktree path overlaps planned path: {path}" for path in overlap)
    elif dirty and not allow_dirty:
        planning_conflicts.append("working tree is dirty; use allow_dirty only for unrelated paths")

    frozen_conflicts = tuple(sorted(set(planning_conflicts)))
    frozen_notices = tuple(sorted(set(notices)))
    frozen_exclusions = tuple(sorted({_validate_relative(path) for path in validation_exclusions}))
    payload = _plan_payload(
        canonical,
        snapshot_sha,
        declaration_identity,
        operations,
        frozen_conflicts,
        frozen_notices,
        frozen_exclusions,
    )
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return TransitionPlan(
        canonical,
        snapshot_sha,
        declaration_identity,
        tuple(operations),
        frozen_conflicts,
        frozen_notices,
        frozen_exclusions,
        digest,
    )


def plan_transition(
    root: Path,
    *,
    snapshot_sha: str,
    declaration_identity: str,
    profile: str,
    pin: str,
    items: Sequence[Any],
    declaration_bytes: bytes,
    force: bool = False,
    baseline_existing_seeds: bool = False,
    allow_fresh_seed_initialization: bool = False,
    allow_seed_set_expansion: bool = False,
    migrating_from: str | None = None,
    source_inventory: ManagedInventory | None = None,
    allow_dirty: bool = True,
) -> PlannedRepositoryTransition:
    """Build the complete local Consumer transition without mutating the worktree."""
    from .inventory import (
        INVENTORY_PATH,
        InventoryRead,
        ManagedInventory,
        load_managed_inventory,
        reconcile_managed_inventory,
        render_managed_inventory,
    )
    from .marker import content_hash, parse_marker_from_text, strip_marker_from_text
    from .pathguard import confined_target
    from .scaffold import (
        SIDECAR_PATH,
        ScaffoldItem,
        inventory_entry_for_item,
        preflight_seed_integrity,
        render_managed,
    )
    from .version import is_known_version_pin

    canonical = _canonical_repo(Path(root))
    overlay: dict[str, ScaffoldItem] = {}
    conflicts: list[str] = []
    notices: list[str] = []
    for raw_item in items:
        if not isinstance(raw_item, ScaffoldItem):
            raise TransitionConflictError("transition items must be ScaffoldItem values")
        _validate_relative(raw_item.output)
        if raw_item.output in {INVENTORY_PATH, SIDECAR_PATH, ".github/aviato.yaml"}:
            conflicts.append(f"artifact output collides with Aviato metadata path: {raw_item.output}")
        overlay[raw_item.output] = raw_item

    seed_items = [item for item in overlay.values() if item.seed_once]
    managed_items = [item for item in overlay.values() if not item.seed_once]
    seed_preflight = preflight_seed_integrity(
        canonical,
        list(overlay.values()),
        baseline_existing_seeds=baseline_existing_seeds,
        allow_fresh_seed_initialization=allow_fresh_seed_initialization,
        allow_seed_set_expansion=allow_seed_set_expansion,
    )
    if seed_preflight.unknown:
        conflicts.append("seed-once integrity is unknown; restore or explicitly rebaseline the seed sidecar")

    changes: list[TransitionChange] = []
    written: list[str] = []
    seeded: list[str] = []
    unchanged: list[str] = []
    preserved_seeds: list[str] = []
    baselined: list[str] = []

    sidecar = {} if baseline_existing_seeds else dict(seed_preflight.sidecar.hashes)
    if baseline_existing_seeds:
        sidecar.update(seed_preflight.existing_hashes)
        baselined.extend(sorted(seed_preflight.existing_hashes))
    sidecar_changed = baseline_existing_seeds
    for item in sorted(seed_items, key=lambda candidate: candidate.output):
        target = confined_target(canonical, item.output, operation="plan seed-once artifact")
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file():
                conflicts.append(f"seed-once path is not a safe regular file: {item.output}")
            else:
                preserved_seeds.append(item.output)
            continue
        changes.append(TransitionChange.write(item.output, item.body.encode("utf-8"), category="seed"))
        sidecar[item.output] = content_hash(item.body)
        sidecar_changed = True
        seeded.append(item.output)

    for item in sorted(managed_items, key=lambda candidate: candidate.output):
        if not item.artifact_id or not item.pipeline_owners:
            conflicts.append(f"managed artifact lacks stable identity or owners: {item.output}")
            continue
        target = confined_target(canonical, item.output, operation="plan managed artifact")
        desired_text = render_managed(item, profile=profile, version=pin)
        should_write = not target.exists()
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file():
                conflicts.append(f"managed target is not a safe regular file: {item.output}")
                continue
            try:
                existing = target.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                if not force:
                    conflicts.append(f"managed target is unreadable or non-text: {item.output}")
                    continue
                existing = ""
            marker = parse_marker_from_text(existing)
            if marker is None:
                if not force:
                    conflicts.append(f"managed target is unmanaged or has a malformed marker: {item.output}")
                    continue
                should_write = True
            else:
                if not force and marker.profile not in {profile, migrating_from}:
                    conflicts.append(f"managed target belongs to foreign profile {marker.profile!r}: {item.output}")
                    continue
                if not force and not is_known_version_pin(marker.version):
                    conflicts.append(f"managed target records unknown version {marker.version!r}: {item.output}")
                    continue
                body_hash = content_hash(strip_marker_from_text(existing))
                if not force and body_hash != marker.hash:
                    conflicts.append(f"managed target is hand-edited: {item.output}")
                    continue
                should_write = existing != desired_text
        if should_write:
            changes.append(TransitionChange.write(item.output, desired_text.encode("utf-8"), category="managed"))
            written.append(item.output)
        else:
            unchanged.append(item.output)

    if sidecar_changed:
        sidecar_bytes = (json.dumps(sidecar, indent=2, sort_keys=True) + "\n").encode("utf-8")
        changes.append(TransitionChange.write(SIDECAR_PATH, sidecar_bytes, category="sidecar"))

    declaration_path = ".github/aviato.yaml"
    declaration_target = confined_target(canonical, declaration_path, operation="plan declaration")
    if not declaration_target.is_file() or declaration_target.read_bytes() != declaration_bytes:
        changes.append(TransitionChange.write(declaration_path, declaration_bytes, category="declaration"))

    prior = load_managed_inventory(canonical)
    if prior.status == "invalid":
        conflicts.append(f"managed inventory is invalid or operator-owned: {prior.reason}")
    effective_prior = (
        InventoryRead("valid", inventory=source_inventory)
        if prior.status == "missing" and source_inventory is not None
        else prior
    )
    entries = {
        item.output: inventory_entry_for_item(item, profile=profile, version=pin)
        for item in managed_items
        if item.artifact_id and item.pipeline_owners
    }
    desired_inventory = ManagedInventory(
        schema_version=1,
        profile=profile,
        profile_identity=declaration_identity,
        pin=pin,
        snapshot_commit=snapshot_sha,
        entries=entries,
        owned_rulesets=(
            effective_prior.inventory.owned_rulesets
            if effective_prior.status == "valid" and effective_prior.inventory
            else ()
        ),
    )
    reconciliation = reconcile_managed_inventory(
        canonical,
        desired_inventory,
        prior=effective_prior,
        source_profile=migrating_from,
        seed_once_paths=frozenset(item.output for item in seed_items),
    )
    for path, reason in reconciliation.obsolete_blocked.items():
        conflicts.append(f"{path}: {reason}")
    for path, candidates in reconciliation.ambiguous.items():
        conflicts.append(f"{path}: legacy identity is ambiguous among {', '.join(candidates)}")
    retired = sorted(set(reconciliation.obsolete_clean) | set(reconciliation.legacy_adoptable))
    for path in retired:
        changes.append(TransitionChange.delete(path, category="managed"))
    notices.extend(f"obsolete managed artifact already absent: {path}" for path in reconciliation.obsolete_missing)
    notices.extend(f"preserved seed-once artifact: {path}" for path in preserved_seeds)
    inventory_bytes = render_managed_inventory(desired_inventory).encode("utf-8")
    inventory_target = confined_target(canonical, INVENTORY_PATH, operation="plan managed inventory")
    if not inventory_target.is_file() or inventory_target.read_bytes() != inventory_bytes:
        changes.append(TransitionChange.write(INVENTORY_PATH, inventory_bytes, category="inventory"))

    plan = build_transition_plan(
        canonical,
        snapshot_sha=snapshot_sha,
        declaration_identity=declaration_identity,
        changes=changes,
        conflicts=conflicts,
        notices=notices,
        allow_dirty=allow_dirty,
    )
    return PlannedRepositoryTransition(
        plan,
        tuple(written),
        tuple(seeded),
        tuple(unchanged),
        tuple(preserved_seeds),
        tuple(baselined),
        tuple(retired),
    )


class _SafeTree:
    def __init__(self, root: Path) -> None:
        self.root = root
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        self.root_fd = os.open(root, flags)
        self.root_stat = os.fstat(self.root_fd)
        live = root.lstat()
        if not stat.S_ISDIR(live.st_mode) or (live.st_dev, live.st_ino) != (
            self.root_stat.st_dev,
            self.root_stat.st_ino,
        ):
            os.close(self.root_fd)
            raise TransitionConflictError("canonical repository root changed during execution")

    def close(self) -> None:
        os.close(self.root_fd)

    def _verify_root_binding(self) -> None:
        try:
            live = self.root.lstat()
        except OSError as exc:
            raise TransitionConflictError("canonical repository root disappeared during execution") from exc
        if not stat.S_ISDIR(live.st_mode) or (live.st_dev, live.st_ino) != (
            self.root_stat.st_dev,
            self.root_stat.st_ino,
        ):
            raise TransitionConflictError("canonical repository root changed during execution")

    def _parent(self, relative: str, *, create: bool = False) -> tuple[int, str]:
        self._verify_root_binding()
        parts = PurePosixPath(_validate_relative(relative)).parts
        current = os.dup(self.root_fd)
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        try:
            for part in parts[:-1]:
                try:
                    child = os.open(part, flags, dir_fd=current)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, 0o755, dir_fd=current)
                    os.fsync(current)
                    child = os.open(part, flags, dir_fd=current)
                except OSError as exc:
                    raise TransitionConflictError(
                        f"parent component is not a stable no-follow directory while confining {relative}"
                    ) from exc
                relative_stat = os.stat(part, dir_fd=current, follow_symlinks=False)
                opened_stat = os.fstat(child)
                if not stat.S_ISDIR(relative_stat.st_mode) or (
                    relative_stat.st_dev,
                    relative_stat.st_ino,
                ) != (opened_stat.st_dev, opened_stat.st_ino):
                    os.close(child)
                    raise TransitionConflictError(f"parent directory changed while confining {relative}")
                os.close(current)
                current = child
            return current, parts[-1]
        except BaseException:
            os.close(current)
            raise

    def _verify_parent_binding(self, relative: str, parent_fd: int) -> None:
        rebound, _name = self._parent(relative)
        try:
            original = os.fstat(parent_fd)
            live = os.fstat(rebound)
            if (original.st_dev, original.st_ino) != (live.st_dev, live.st_ino):
                raise TransitionConflictError(f"target parent changed immediately before mutating {relative}")
        finally:
            os.close(rebound)

    def fingerprint(self, relative: str) -> FileFingerprint:
        try:
            parent, name = self._parent(relative)
        except FileNotFoundError:
            return FileFingerprint("missing")
        try:
            try:
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return FileFingerprint("missing")
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                return FileFingerprint("unsafe")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(name, flags, dir_fd=parent)
            try:
                opened = os.fstat(fd)
                if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                    raise TransitionConflictError(f"target changed while fingerprinting {relative}")
                digest = hashlib.sha256()
                size = 0
                while True:
                    block = os.read(fd, 1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
                    size += len(block)
                return FileFingerprint("file", digest.hexdigest(), stat.S_IMODE(opened.st_mode), size)
            finally:
                os.close(fd)
        finally:
            os.close(parent)

    def read(self, relative: str, expected: FileFingerprint) -> bytes:
        if expected.kind != "file":
            return b""
        parent, name = self._parent(relative)
        try:
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
            try:
                chunks: list[bytes] = []
                while block := os.read(fd, 1024 * 1024):
                    chunks.append(block)
                payload = b"".join(chunks)
            finally:
                os.close(fd)
        finally:
            os.close(parent)
        fingerprint = FileFingerprint("file", hashlib.sha256(payload).hexdigest(), expected.mode, len(payload))
        if fingerprint.sha256 != expected.sha256 or fingerprint.size != expected.size:
            raise TransitionConflictError(f"target changed while reading preimage: {relative}")
        return payload

    def _snapshot_leaf(
        self,
        parent: int,
        name: str,
        relative: str,
    ) -> tuple[FileFingerprint, bytes | None, int | None]:
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return FileFingerprint("missing"), None, None
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            return FileFingerprint("unsafe"), None, None
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
        try:
            opened = os.fstat(fd)
            if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                raise TransitionConflictError(f"target changed while snapshotting {relative}")
            chunks: list[bytes] = []
            digest = hashlib.sha256()
            size = 0
            while block := os.read(fd, 1024 * 1024):
                chunks.append(block)
                digest.update(block)
                size += len(block)
            mode = stat.S_IMODE(opened.st_mode)
            return FileFingerprint("file", digest.hexdigest(), mode, size), b"".join(chunks), mode
        finally:
            os.close(fd)

    def _restore_leaf_snapshot(
        self,
        parent: int,
        name: str,
        payload: bytes | None,
        mode: int | None,
        operation: TransitionOperation,
    ) -> None:
        if payload is None:
            with suppress(FileNotFoundError):
                os.unlink(name, dir_fd=parent)
            os.fsync(parent)
            return
        assert mode is not None
        temporary = f".aviato-transition-compensate-{operation.operation_id}-{uuid.uuid4().hex}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
        installed = False
        try:
            _write_all(fd, payload)
            os.fchmod(fd, mode)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            installed = True
            os.fsync(parent)
        finally:
            if fd >= 0:
                os.close(fd)
            if not installed:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=parent)

    def replace(
        self,
        relative: str,
        payload: bytes,
        mode: int,
        fault: FaultHook,
        operation: TransitionOperation,
        expected_live: FileFingerprint,
        temporary: str,
        *,
        recovering: bool = False,
    ) -> None:
        parent, name = self._parent(relative, create=True)
        if PurePosixPath(temporary).name != temporary or not temporary.startswith(".aviato-transition-"):
            os.close(parent)
            raise TransitionRecoveryError("journal recorded an invalid staged temporary name")
        if recovering:
            self._discard_temp_from_parent(parent, temporary, relative)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temporary, flags, 0o600, dir_fd=parent)
        installed = False
        try:
            fault("temp_created", operation)
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write while staging transition target")
                view = view[written:]
            os.fchmod(fd, mode)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            fault("temp_fsync", operation)
            fault("before_mutation_syscall", operation)
            if self.fingerprint(relative) != expected_live:
                raise TransitionConflictError(f"target fingerprint changed immediately before replacing {relative}")
            self._verify_parent_binding(relative, parent)
            retained_fingerprint, retained_payload, retained_mode = self._snapshot_leaf(parent, name, relative)
            if retained_fingerprint != expected_live:
                raise TransitionConflictError(f"target changed in retained parent before replacing {relative}")
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            installed = True
            try:
                self._verify_parent_binding(relative, parent)
            except TransitionConflictError as exc:
                try:
                    self._restore_leaf_snapshot(parent, name, retained_payload, retained_mode, operation)
                except Exception as compensation_exc:
                    raise TransitionRecoveryError(
                        f"target parent changed while replacing {relative}; compensating restore failed: "
                        f"{compensation_exc}"
                    ) from exc
                raise TransitionConflictError(
                    f"target parent changed during replace of {relative}; mutation was compensated"
                ) from exc
            fault("mutation", operation)
            os.fsync(parent)
            fault("target_dir_fsync", operation)
        finally:
            if fd >= 0:
                os.close(fd)
            if not installed:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=parent)
            os.close(parent)

    def _discard_temp_from_parent(
        self,
        parent: int,
        temporary: str,
        relative: str,
    ) -> None:
        try:
            info = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise TransitionRecoveryError(f"unsafe staged temporary file for {relative}")
        os.unlink(temporary, dir_fd=parent)
        os.fsync(parent)

    def discard_operation_temp(self, operation: TransitionOperation, temporary: str) -> None:
        if operation.kind != "replace":
            return
        try:
            parent, _name = self._parent(operation.path)
        except FileNotFoundError:
            return
        try:
            self._discard_temp_from_parent(
                parent,
                temporary,
                operation.path,
            )
        finally:
            os.close(parent)

    def delete(
        self,
        relative: str,
        fault: FaultHook,
        operation: TransitionOperation,
        expected_live: FileFingerprint,
    ) -> None:
        try:
            parent, name = self._parent(relative)
        except FileNotFoundError:
            if expected_live != FileFingerprint("missing"):
                raise TransitionConflictError(
                    f"target parent disappeared immediately before deleting {relative}"
                ) from None
            fault("mutation", operation)
            fault("target_dir_fsync", operation)
            return
        try:
            fault("before_mutation_syscall", operation)
            if self.fingerprint(relative) != expected_live:
                raise TransitionConflictError(f"target fingerprint changed immediately before deleting {relative}")
            self._verify_parent_binding(relative, parent)
            retained_fingerprint, retained_payload, retained_mode = self._snapshot_leaf(parent, name, relative)
            if retained_fingerprint != expected_live:
                raise TransitionConflictError(f"target changed in retained parent before deleting {relative}")
            with suppress(FileNotFoundError):
                os.unlink(name, dir_fd=parent)
            try:
                self._verify_parent_binding(relative, parent)
            except TransitionConflictError as exc:
                try:
                    self._restore_leaf_snapshot(parent, name, retained_payload, retained_mode, operation)
                except Exception as compensation_exc:
                    raise TransitionRecoveryError(
                        f"target parent changed while deleting {relative}; compensating restore failed: "
                        f"{compensation_exc}"
                    ) from exc
                raise TransitionConflictError(
                    f"target parent changed during delete of {relative}; mutation was compensated"
                ) from exc
            fault("mutation", operation)
            os.fsync(parent)
            fault("target_dir_fsync", operation)
        finally:
            os.close(parent)

    def remove_empty_dirs(self, relative_directories: Sequence[str]) -> None:
        for relative in sorted(relative_directories, key=lambda value: len(PurePosixPath(value).parts), reverse=True):
            parts = PurePosixPath(relative).parts
            if not parts:
                continue
            try:
                parent, name = self._parent(relative)
            except (FileNotFoundError, TransitionConflictError):
                continue
            try:
                try:
                    os.rmdir(name, dir_fd=parent)
                    os.fsync(parent)
                except OSError as exc:
                    if exc.errno not in {errno.ENOTEMPTY, errno.ENOENT}:
                        raise
            finally:
                os.close(parent)


def _state_paths(root: Path) -> tuple[Path, Path, str]:
    git_dir = _single_git_path(root, "rev-parse", "--path-format=absolute", "--git-dir")
    git_path = _single_git_path(root, "rev-parse", "--path-format=absolute", "--git-path", "aviato-transitions")
    if not git_dir.is_absolute() or not git_path.is_absolute():
        raise TransitionRecoveryError("Git administrative paths must be absolute")
    try:
        git_dir_stat = git_dir.lstat()
    except OSError as exc:
        raise TransitionRecoveryError(f"could not inspect per-worktree Git directory: {exc}") from exc
    if not stat.S_ISDIR(git_dir_stat.st_mode) or stat.S_ISLNK(git_dir_stat.st_mode):
        raise TransitionRecoveryError("per-worktree Git directory is not a no-follow directory")
    namespace_source = (f"{root}\0{git_dir}\0{git_dir_stat.st_dev}\0{git_dir_stat.st_ino}").encode()
    namespace = hashlib.sha256(namespace_source).hexdigest()[:24]
    state = git_path / namespace
    try:
        state.relative_to(git_dir)
    except ValueError as exc:
        raise TransitionRecoveryError("Git transition state path escapes the per-worktree Git directory") from exc
    return state, git_dir, namespace


def _open_or_create_admin_state(git_dir: Path, state: Path, *, create: bool = True) -> int:
    try:
        relative = state.relative_to(git_dir)
    except ValueError as exc:
        raise TransitionRecoveryError("transition state is outside Git administration") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        current = os.open(git_dir, flags)
    except OSError as exc:
        raise TransitionRecoveryError(f"could not securely open Git administration: {exc}") from exc
    try:
        for component in relative.parts:
            try:
                child = os.open(component, flags, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o700, dir_fd=current)
                os.fsync(current)
                child = os.open(component, flags, dir_fd=current)
            except OSError as exc:
                raise TransitionRecoveryError(
                    f"Git transition state component {component!r} is not a no-follow directory"
                ) from exc
            relative_stat = os.stat(component, dir_fd=current, follow_symlinks=False)
            opened_stat = os.fstat(child)
            if not stat.S_ISDIR(relative_stat.st_mode) or (
                relative_stat.st_dev,
                relative_stat.st_ino,
            ) != (opened_stat.st_dev, opened_stat.st_ino):
                os.close(child)
                raise TransitionRecoveryError("Git transition state changed during secure traversal")
            os.close(current)
            current = child
        os.fsync(current)
        return current
    except BaseException:
        os.close(current)
        raise


def _open_child_directory(parent_fd: int, name: str, *, create: bool) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        child = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        os.fsync(parent_fd)
        child = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise TransitionRecoveryError(f"Git transition state component {name!r} is not a no-follow directory") from exc
    relative_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    opened_stat = os.fstat(child)
    if not stat.S_ISDIR(relative_stat.st_mode) or (
        relative_stat.st_dev,
        relative_stat.st_ino,
    ) != (opened_stat.st_dev, opened_stat.st_ino):
        os.close(child)
        raise TransitionRecoveryError("Git transition state changed during secure traversal")
    return child


def _open_journals_directory(state: Path, *, create: bool) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        state_fd = os.open(state, flags)
    except OSError as exc:
        raise TransitionRecoveryError(f"could not securely reopen transition state: {exc}") from exc
    try:
        return _open_child_directory(state_fd, "journals", create=create)
    finally:
        os.close(state_fd)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _transition_lock(root: Path, *, recovery: bool) -> Any:
    state, git_dir, namespace = _state_paths(root)
    state_fd = _open_or_create_admin_state(git_dir, state, create=True)
    try:
        journals_fd = _open_child_directory(state_fd, "journals", create=True)
    except BaseException:
        os.close(state_fd)
        raise
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open("execution.lock", flags, 0o600, dir_fd=state_fd)
    except BaseException:
        os.close(journals_fd)
        os.close(state_fd)
        raise
    try:
        state_handle = _TransitionState(state, state_fd, journals_fd)
        lock_stat = os.fstat(fd)
        if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != os.geteuid() or lock_stat.st_nlink != 1:
            raise TransitionRecoveryError("transition lock is not a private, owned regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TransitionRecoveryError("repository transition is locked by another live process") from exc
        previous = os.read(fd, 64 * 1024)
        if previous:
            try:
                metadata = _unique_json(previous, context="transition lock metadata")
            except TransitionRecoveryError:
                if _pending_journals(state_handle) and not recovery:
                    raise TransitionRecoveryError("corrupt stale transition lock requires explicit recovery") from None
            else:
                if (
                    not isinstance(metadata, dict)
                    or metadata.get("root") != str(root)
                    or metadata.get("namespace") != namespace
                ):
                    raise TransitionRecoveryError("transition lock ownership does not match this worktree")
                if (
                    not recovery
                    and metadata.get("active") is True
                    and metadata.get("pid") != os.getpid()
                    and _pending_journals(state_handle)
                ):
                    # An unlocked active record is stale evidence from process death. Only
                    # an explicitly confirmed recovery path may claim it while journal
                    # evidence remains. With no journal, terminal cleanup already reached
                    # its durable end and the unlocked stale owner record can be replaced.
                    raise TransitionRecoveryError("stale transition lock requires explicit recovery")
        record = {
            "schema": _STATE_SCHEMA,
            "root": str(root),
            "git_dir": str(git_dir),
            "namespace": namespace,
            "pid": os.getpid(),
            "active": True,
        }
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        _write_all(fd, _canonical_json(record))
        os.fsync(fd)
        try:
            yield state_handle
        finally:
            # In-process exceptions and interruptions release the live lock
            # cleanly while retaining any journal. SIGKILL cannot run this block,
            # so its active owner record remains useful stale-process evidence.
            record["active"] = False
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            _write_all(fd, _canonical_json(record))
            os.fsync(fd)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
            os.close(journals_fd)
            os.close(state_fd)


@contextmanager
def _existing_transition_state(root: Path) -> Any:
    state, git_dir, _namespace = _state_paths(root)
    state_fd = _open_or_create_admin_state(git_dir, state, create=False)
    try:
        journals_fd = _open_child_directory(state_fd, "journals", create=False)
    except BaseException:
        os.close(state_fd)
        raise
    try:
        yield _TransitionState(state, state_fd, journals_fd)
    finally:
        os.close(journals_fd)
        os.close(state_fd)


def _manifest_data(plan: TransitionPlan, journal_id: str, created_dirs: Sequence[str]) -> dict[str, object]:
    payload = _plan_payload(
        plan.canonical_root,
        plan.snapshot_sha,
        plan.declaration_identity,
        plan.operations,
        plan.conflicts,
        plan.notices,
        plan.validation_exclusions,
    )
    core = {
        "schema": _STATE_SCHEMA,
        "journal_id": journal_id,
        "plan_digest": plan.digest,
        "plan": payload,
        "created_dirs": list(created_dirs),
    }
    return {**core, "manifest_digest": hashlib.sha256(_canonical_json(core)).hexdigest()}


def _missing_parent_dirs(plan: TransitionPlan) -> tuple[str, ...]:
    missing: set[str] = set()
    for operation in plan.operations:
        current = plan.canonical_root
        parts = PurePosixPath(operation.path).parts[:-1]
        accumulated: list[str] = []
        for part in parts:
            accumulated.append(part)
            current = current / part
            if not current.exists():
                missing.add(PurePosixPath(*accumulated).as_posix())
    return tuple(sorted(missing))


def _open_journal_fd(journal: _JournalRef) -> int:
    return _open_child_directory(journal.state.journals_fd, journal.name, create=False)


def _read_regular_at(parent_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise TransitionRecoveryError(f"private journal file {name!r} is not an owned regular file")
        chunks: list[bytes] = []
        while block := os.read(fd, 1024 * 1024):
            chunks.append(block)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _journal_file_exists(journal: _JournalRef, name: str) -> bool:
    journal_fd = _open_journal_fd(journal)
    try:
        try:
            info = os.stat(name, dir_fd=journal_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
    finally:
        os.close(journal_fd)


def _create_journal(
    state: _TransitionState,
    plan: TransitionPlan,
    fault: FaultHook,
) -> tuple[_JournalRef, str]:
    journal_id = uuid.uuid4().hex
    staging_name = f".staging-{journal_id}"
    os.mkdir(staging_name, 0o700, dir_fd=state.journals_fd)
    staging_fd = _open_child_directory(state.journals_fd, staging_name, create=False)
    os.mkdir("preimages", 0o700, dir_fd=staging_fd)
    os.fsync(staging_fd)
    manifest = _manifest_data(plan, journal_id, _missing_parent_dirs(plan))
    fd = os.open(
        "manifest.json",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=staging_fd,
    )
    try:
        payload = _canonical_json(manifest) + b"\n"
        _write_all(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(staging_fd)
    os.close(staging_fd)
    os.rename(staging_name, journal_id, src_dir_fd=state.journals_fd, dst_dir_fd=state.journals_fd)
    os.fsync(state.journals_fd)
    fault("journal_dir_fsync", None)
    fault("manifest_fsync", None)
    return _JournalRef(state, journal_id), journal_id


def _append_event(
    journal: _JournalRef,
    phase: str,
    operation_id: str,
    fault: FaultHook,
    operation: TransitionOperation | None,
    *,
    temp_name: str = "",
) -> None:
    events = _load_events(journal, repair_torn_tail=True)
    core = {
        "sequence": len(events) + 1,
        "phase": phase,
        "operation_id": operation_id,
        "temp_name": temp_name,
    }
    checksum = hashlib.sha256(_canonical_json(core)).hexdigest()
    payload = _canonical_json({**core, "checksum": checksum}) + b"\n"
    journal_fd = _open_journal_fd(journal)
    fd = os.open(
        "events.jsonl",
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=journal_fd,
    )
    try:
        _write_all(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
        os.close(journal_fd)
    fault(phase.lower() + "_fsync", operation)


def _load_events(journal: _JournalRef, *, repair_torn_tail: bool = False) -> list[dict[str, object]]:
    journal_fd = _open_journal_fd(journal)
    try:
        payload = _read_regular_at(journal_fd, "events.jsonl")
    except FileNotFoundError:
        os.close(journal_fd)
        return []
    lines = payload.splitlines(keepends=True)
    torn_tail = False
    if lines and not lines[-1].endswith(b"\n"):
        lines.pop()
        torn_tail = True
    valid_length = sum(len(line) for line in lines)
    events: list[dict[str, object]] = []
    for expected_sequence, line in enumerate(lines, 1):
        try:
            value = _unique_json(line, context="transition journal event")
        except TransitionRecoveryError as exc:
            raise TransitionRecoveryError("transition journal contains a malformed complete event") from exc
        if not isinstance(value, dict) or set(value) != {
            "sequence",
            "phase",
            "operation_id",
            "temp_name",
            "checksum",
        }:
            raise TransitionRecoveryError("transition journal event has an invalid schema")
        if not isinstance(value["temp_name"], str):
            raise TransitionRecoveryError("transition journal event has invalid temporary metadata")
        checksum = value.pop("checksum")
        if value.get("sequence") != expected_sequence or checksum != hashlib.sha256(_canonical_json(value)).hexdigest():
            raise TransitionRecoveryError("transition journal event sequence or checksum is invalid")
        value["checksum"] = checksum
        events.append(value)
    if torn_tail and repair_torn_tail:
        fd = os.open("events.jsonl", os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), dir_fd=journal_fd)
        try:
            os.ftruncate(fd, valid_length)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(journal_fd)
    os.close(journal_fd)
    return events


def _new_operation_temp(journal_id: str, operation: TransitionOperation) -> str:
    return f".aviato-transition-{journal_id}-{operation.operation_id}-{uuid.uuid4().hex}.tmp"


def _authenticated_operation_temps(
    journal: _JournalRef,
    journal_id: str,
    operation: TransitionOperation,
) -> tuple[str, ...]:
    prefix = f".aviato-transition-{journal_id}-{operation.operation_id}-"
    result: list[str] = []
    for event in _load_events(journal, repair_torn_tail=True):
        if event["phase"] != "PREPARED" or event["operation_id"] != operation.operation_id:
            continue
        temp_name = event["temp_name"]
        if operation.kind == "delete":
            if temp_name != "":
                raise TransitionRecoveryError("delete intent records unexpected temporary metadata")
            continue
        if not isinstance(temp_name, str) or not temp_name.startswith(prefix) or not temp_name.endswith(".tmp"):
            raise TransitionRecoveryError("replace intent records invalid temporary metadata")
        nonce = temp_name[len(prefix) : -4]
        if len(nonce) != 32 or any(character not in "0123456789abcdef" for character in nonce):
            raise TransitionRecoveryError("replace intent records invalid temporary identity")
        result.append(temp_name)
    return tuple(dict.fromkeys(result))


def _write_preimage(
    journal: _JournalRef,
    tree: _SafeTree,
    operation: TransitionOperation,
    fault: FaultHook,
) -> None:
    journal_fd = _open_journal_fd(journal)
    backups_fd = _open_child_directory(journal_fd, "preimages", create=False)
    os.close(journal_fd)
    if operation.expected.kind != "file":
        try:
            os.stat(operation.operation_id, dir_fd=backups_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            os.close(backups_fd)
            raise TransitionRecoveryError(f"unexpected preimage backup for absent path {operation.path}")
        fault("preimage_fsync", operation)
        fault("backup_dir_fsync", operation)
        os.close(backups_fd)
        return
    payload = tree.read(operation.path, operation.expected)
    write_backup = False
    try:
        backup_info = os.stat(operation.operation_id, dir_fd=backups_fd, follow_symlinks=False)
    except FileNotFoundError:
        write_backup = True
    else:
        if (
            not stat.S_ISREG(backup_info.st_mode)
            or stat.S_ISLNK(backup_info.st_mode)
            or backup_info.st_nlink != 1
            or backup_info.st_uid != os.geteuid()
        ):
            os.close(backups_fd)
            raise TransitionRecoveryError(f"unsafe preimage backup for {operation.path}")
        try:
            _read_preimage(journal, operation)
        except TransitionRecoveryError:
            # The caller has just re-confined and proven the live target still
            # equals the expected preimage, so a journal-owned torn backup can
            # be discarded and recreated without losing recovery evidence.
            os.unlink(operation.operation_id, dir_fd=backups_fd)
            os.fsync(backups_fd)
            write_backup = True
    if write_backup:
        fd = os.open(
            operation.operation_id,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=backups_fd,
        )
        try:
            fault("preimage_created", operation)
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
    fault("preimage_fsync", operation)
    os.fsync(backups_fd)
    os.close(backups_fd)
    fault("backup_dir_fsync", operation)


def _read_preimage(journal: _JournalRef, operation: TransitionOperation) -> bytes:
    if operation.expected.kind != "file":
        return b""
    journal_fd = _open_journal_fd(journal)
    backups_fd = _open_child_directory(journal_fd, "preimages", create=False)
    os.close(journal_fd)
    try:
        payload = _read_regular_at(backups_fd, operation.operation_id)
    except OSError as exc:
        raise TransitionRecoveryError(f"could not read preimage backup for {operation.path}: {exc}") from exc
    finally:
        os.close(backups_fd)
    if hashlib.sha256(payload).hexdigest() != operation.expected.sha256 or len(payload) != operation.expected.size:
        raise TransitionRecoveryError(f"preimage backup hash mismatch for {operation.path}")
    return payload


def _perform_operation(
    tree: _SafeTree,
    operation: TransitionOperation,
    fault: FaultHook,
    temporary: str,
    *,
    recovering: bool = False,
) -> None:
    if operation.kind == "delete":
        tree.delete(operation.path, fault, operation, operation.expected)
    else:
        assert operation.desired_bytes is not None and operation.mode is not None
        tree.replace(
            operation.path,
            operation.desired_bytes,
            operation.mode,
            fault,
            operation,
            operation.expected,
            temporary,
            recovering=recovering,
        )


def _default_validate(root: Path, plan: TransitionPlan) -> bool:
    tree = _SafeTree(root)
    try:
        if not all(tree.fingerprint(operation.path) == operation.desired for operation in plan.operations):
            return False
    finally:
        tree.close()
    inventory_operations = [operation for operation in plan.operations if operation.category == "inventory"]
    if not inventory_operations:
        return True
    from .inventory import (
        INVENTORY_PATH,
        InventoryRead,
        load_managed_inventory,
        reconcile_managed_inventory,
        scan_marker_universe,
    )
    from .scaffold import read_sidecar

    if len(inventory_operations) != 1 or inventory_operations[0].path != INVENTORY_PATH:
        return False
    inventory_read = load_managed_inventory(root)
    if inventory_operations[0].kind == "delete":
        excluded = {_path_identity(path) for path in plan.validation_exclusions}
        remaining = {
            path: artifact
            for path, artifact in scan_marker_universe(root).items()
            if _path_identity(path) not in excluded
        }
        return inventory_read.status == "missing" and not remaining
    if inventory_read.status != "valid" or inventory_read.inventory is None:
        return False
    if (
        inventory_read.inventory.snapshot_commit != plan.snapshot_sha
        or inventory_read.inventory.profile_identity != plan.declaration_identity
    ):
        return False
    sidecar = read_sidecar(root)
    seed_once_paths = frozenset(sidecar.hashes) if sidecar.status == "ok" else frozenset()
    seed_identities = {_path_identity(path) for path in seed_once_paths}
    universe = {
        path: artifact
        for path, artifact in scan_marker_universe(root).items()
        if _path_identity(path) not in seed_identities
    }
    for path, entry in inventory_read.inventory.entries.items():
        artifact = universe.get(path)
        if (
            artifact is None
            or artifact.status != "valid"
            or artifact.marker is None
            or artifact.marker.profile != inventory_read.inventory.profile
            or artifact.marker.version != inventory_read.inventory.pin
            or artifact.marker.input_hash != entry.input_hash
            or artifact.marker.hash != entry.body_hash
            or artifact.marker_line_hash != entry.marker_hash
            or artifact.live_body_hash != entry.body_hash
        ):
            return False
    reconciliation = reconcile_managed_inventory(
        root,
        inventory_read.inventory,
        prior=InventoryRead("valid", inventory=inventory_read.inventory),
        seed_once_paths=seed_once_paths,
    )
    return not (
        reconciliation.obsolete_clean
        or reconciliation.obsolete_missing
        or reconciliation.obsolete_blocked
        or reconciliation.legacy_adoptable
        or reconciliation.ambiguous
    )


def _validator_with_internal_check(validate: Validator | None) -> Validator:
    if validate is None:
        return _default_validate

    def combined(root: Path, plan: TransitionPlan) -> bool:
        return _default_validate(root, plan) and validate(root, plan)

    return combined


def _restore_operation(
    tree: _SafeTree,
    journal: _JournalRef,
    operation: TransitionOperation,
    temporary: str,
) -> None:
    def quiet(_phase: str, _operation: TransitionOperation | None) -> None:
        return None

    if operation.expected.kind == "missing":
        tree.delete(operation.path, quiet, operation, operation.desired)
    elif operation.expected.kind == "file":
        payload = _read_preimage(journal, operation)
        assert operation.expected.mode is not None
        restore_temporary = temporary or _new_operation_temp(journal.name, operation)
        tree.replace(
            operation.path,
            payload,
            operation.expected.mode,
            quiet,
            operation,
            operation.desired,
            restore_temporary,
            recovering=True,
        )
    else:
        raise TransitionRecoveryError(f"cannot restore unsafe preimage for {operation.path}")


def _result(
    plan: TransitionPlan,
    journal_id: str,
    statuses: dict[str, tuple[OperationStatus, str]],
    *,
    accepted: bool,
) -> TransitionResult:
    return TransitionResult(
        journal_id,
        plan.digest,
        tuple(
            OperationResult(
                operation.operation_id,
                operation.kind,
                operation.path,
                statuses.get(operation.operation_id, (OperationStatus.UNATTEMPTED, ""))[0],
                statuses.get(operation.operation_id, (OperationStatus.UNATTEMPTED, ""))[1],
                operation.expected,
                operation.desired,
            )
            for operation in plan.operations
        ),
        accepted,
    )


def _cleanup_journal(journal: _JournalRef, fault: FaultHook, *, terminal: str) -> None:
    terminal_name = f".terminal-{terminal}-{journal.name}"
    os.rename(
        journal.name,
        terminal_name,
        src_dir_fd=journal.state.journals_fd,
        dst_dir_fd=journal.state.journals_fd,
    )
    os.fsync(journal.state.journals_fd)
    fault("journal_terminal_fsync", None)
    _remove_terminal_journal(_JournalRef(journal.state, terminal_name), fault)


def _remove_terminal_journal(journal: _JournalRef, fault: FaultHook) -> None:
    journal_fd = _open_journal_fd(journal)
    for name in ("events.jsonl", "manifest.json"):
        with suppress(FileNotFoundError):
            os.unlink(name, dir_fd=journal_fd)
    try:
        backups_fd = _open_child_directory(journal_fd, "preimages", create=False)
    except FileNotFoundError:
        backups_fd = -1
    if backups_fd >= 0:
        for child in os.listdir(backups_fd):
            info = os.stat(child, dir_fd=backups_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise TransitionRecoveryError("transition preimage directory contains an unsafe entry")
            os.unlink(child, dir_fd=backups_fd)
        os.fsync(backups_fd)
        os.close(backups_fd)
        os.rmdir("preimages", dir_fd=journal_fd)
    os.fsync(journal_fd)
    os.close(journal_fd)
    os.rmdir(journal.name, dir_fd=journal.state.journals_fd)
    os.fsync(journal.state.journals_fd)
    fault("journal_parent_fsync", None)


def _execute_new_locked(
    state: _TransitionState,
    plan: TransitionPlan,
    validate: Validator,
    fault: FaultHook,
) -> TransitionResult:
    tree = _SafeTree(plan.canonical_root)
    try:
        for operation in plan.operations:
            fault("before_reconfine", operation)
            if tree.fingerprint(operation.path) != operation.expected:
                raise TransitionConflictError(f"planned fingerprint changed before mutation: {operation.path}")
        try:
            journal, journal_id = _create_journal(state, plan, fault)
        except Exception as exc:
            pending = _pending_journals(state)
            if len(pending) == 1:
                manifest = _load_manifest(pending[0])
                if manifest["plan_digest"] == plan.digest:
                    _cleanup_journal(pending[0], lambda _phase, _operation: None, terminal="rolledback")
            initialization_statuses = {
                operation.operation_id: (
                    OperationStatus.FAILED if index == 0 else OperationStatus.UNATTEMPTED,
                    str(exc) if index == 0 else "not attempted",
                )
                for index, operation in enumerate(plan.operations)
            }
            result = _result(plan, "", initialization_statuses, accepted=False)
            raise TransitionExecutionError(
                f"transition journal initialization failed before mutation: {exc}", result
            ) from exc
        statuses: dict[str, tuple[OperationStatus, str]] = {}
        current: TransitionOperation | None = None
        accepted = False
        try:
            for operation in plan.operations:
                current = operation
                fault("before_reconfine", operation)
                if tree.fingerprint(operation.path) != operation.expected:
                    raise TransitionConflictError(f"planned fingerprint changed before mutation: {operation.path}")
                _write_preimage(journal, tree, operation, fault)
                temporary = _new_operation_temp(journal_id, operation) if operation.kind == "replace" else ""
                _append_event(
                    journal,
                    "PREPARED",
                    operation.operation_id,
                    fault,
                    operation,
                    temp_name=temporary,
                )
                _perform_operation(tree, operation, fault, temporary)
                if tree.fingerprint(operation.path) != operation.desired:
                    raise TransitionError(f"operation did not produce its desired fingerprint: {operation.path}")
                _append_event(journal, "APPLIED", operation.operation_id, fault, operation)
                statuses[operation.operation_id] = (OperationStatus.COMPLETED, "applied")
            fault("final_diagnosis", None)
            if not validate(plan.canonical_root, plan):
                raise TransitionError("final local convergence diagnosis rejected the transition")
            _append_event(journal, "ACCEPTED", "", fault, None)
            accepted = True
            _cleanup_journal(journal, fault, terminal="accepted")
            return _result(plan, journal_id, statuses, accepted=True)
        except Exception as exc:
            if accepted or _journal_accepted(journal):
                result = _result(plan, journal_id, statuses, accepted=True)
                raise TransitionExecutionError(
                    f"transition was accepted but private journal cleanup is incomplete: {exc}",
                    result,
                ) from exc
            failed_id = current.operation_id if current is not None else ""
            rollback_error: Exception | None = None
            try:
                for operation in reversed(plan.operations):
                    live = tree.fingerprint(operation.path)
                    if live == operation.expected:
                        continue
                    if live == operation.desired:
                        temporary = (
                            _authenticated_operation_temps(journal, journal_id, operation)[-1]
                            if operation.kind == "replace"
                            else ""
                        )
                        _restore_operation(tree, journal, operation, temporary)
                    else:
                        raise TransitionRecoveryError(
                            f"rollback found {operation.path} matching neither preimage nor desired state"
                        )
                manifest = _load_manifest(journal)
                tree.remove_empty_dirs(tuple(manifest["created_dirs"]))
                if any(tree.fingerprint(operation.path) != operation.expected for operation in plan.operations):
                    raise TransitionRecoveryError("rollback verification did not restore every preimage")
                _cleanup_journal(journal, lambda _phase, _operation: None, terminal="rolledback")
            except Exception as rollback_exc:
                rollback_error = rollback_exc
            rolled_back = {
                operation.operation_id: (
                    OperationStatus.FAILED if operation.operation_id == failed_id else OperationStatus.UNATTEMPTED,
                    str(exc) if operation.operation_id == failed_id else "rolled back or not attempted",
                )
                for operation in plan.operations
            }
            result = _result(plan, journal_id, rolled_back, accepted=False)
            if rollback_error is not None:
                raise TransitionExecutionError(
                    f"transition failed ({exc}); rollback is incomplete ({rollback_error}); explicit recovery required",
                    result,
                ) from exc
            if isinstance(exc, TransitionConflictError) and not statuses:
                raise exc
            raise TransitionExecutionError(f"transition failed and was rolled back: {exc}", result) from exc
    finally:
        tree.close()


def _load_manifest(journal: _JournalRef) -> dict[str, Any]:
    journal_fd = _open_journal_fd(journal)
    try:
        raw = _read_regular_at(journal_fd, "manifest.json")
        if len(raw) > 64 * 1024 * 1024:
            raise TransitionRecoveryError("transition manifest exceeds the safety limit")
        value = _unique_json(raw, context="transition manifest")
    except (OSError, TransitionRecoveryError) as exc:
        raise TransitionRecoveryError(f"could not read transition manifest: {exc}") from exc
    finally:
        os.close(journal_fd)
    required = {"schema", "journal_id", "plan_digest", "plan", "created_dirs", "manifest_digest"}
    if not isinstance(value, dict) or set(value) != required or value.get("schema") != _STATE_SCHEMA:
        raise TransitionRecoveryError("transition manifest has an invalid schema")
    manifest_digest = value["manifest_digest"]
    if not isinstance(manifest_digest, str) or len(manifest_digest) != 64:
        raise TransitionRecoveryError("transition manifest has an invalid digest")
    core = {key: item for key, item in value.items() if key != "manifest_digest"}
    if hashlib.sha256(_canonical_json(core)).hexdigest() != manifest_digest:
        raise TransitionRecoveryError("transition manifest digest is invalid")
    if (
        not isinstance(value["journal_id"], str)
        or len(value["journal_id"]) != 32
        or any(character not in "0123456789abcdef" for character in value["journal_id"])
        or not isinstance(value["plan_digest"], str)
        or len(value["plan_digest"]) != 64
    ):
        raise TransitionRecoveryError("transition manifest has invalid identity metadata")
    if not isinstance(value["created_dirs"], list) or any(not isinstance(item, str) for item in value["created_dirs"]):
        raise TransitionRecoveryError("transition manifest has invalid directory metadata")
    return value


def _plan_from_manifest(manifest: dict[str, Any]) -> TransitionPlan:
    payload = manifest["plan"]
    if not isinstance(payload, dict) or set(payload) != {
        "canonical_root",
        "snapshot_sha",
        "declaration_identity",
        "operations",
        "conflicts",
        "notices",
        "validation_exclusions",
    }:
        raise TransitionRecoveryError("transition manifest plan has an invalid schema")
    if (
        not isinstance(payload["canonical_root"], str)
        or not isinstance(payload["snapshot_sha"], str)
        or not isinstance(payload["declaration_identity"], str)
        or not isinstance(payload["conflicts"], list)
        or any(not isinstance(item, str) for item in payload["conflicts"])
        or not isinstance(payload["notices"], list)
        or any(not isinstance(item, str) for item in payload["notices"])
        or not isinstance(payload["validation_exclusions"], list)
        or any(not isinstance(item, str) for item in payload["validation_exclusions"])
    ):
        raise TransitionRecoveryError("transition manifest plan metadata has invalid types")
    operations: list[TransitionOperation] = []
    if not isinstance(payload["operations"], list):
        raise TransitionRecoveryError("transition manifest operations are invalid")
    for raw in payload["operations"]:
        if not isinstance(raw, dict) or set(raw) != {
            "operation_id",
            "kind",
            "path",
            "category",
            "desired_bytes",
            "mode",
            "expected",
        }:
            raise TransitionRecoveryError("transition manifest operation has an invalid schema")
        if (
            not isinstance(raw["operation_id"], str)
            or not isinstance(raw["path"], str)
            or not isinstance(raw["category"], str)
            or not isinstance(raw["kind"], str)
            or (raw["mode"] is not None and type(raw["mode"]) is not int)
            or (raw["desired_bytes"] is not None and not isinstance(raw["desired_bytes"], str))
        ):
            raise TransitionRecoveryError("transition manifest operation has invalid field types")
        try:
            desired = (
                base64.b64decode(raw["desired_bytes"], validate=True) if raw["desired_bytes"] is not None else None
            )
        except (TypeError, ValueError) as exc:
            raise TransitionRecoveryError("transition manifest has invalid desired bytes") from exc
        path = _validate_relative(raw["path"])
        if raw["kind"] not in {"replace", "delete"} or raw["category"] not in _CATEGORY_ORDER:
            raise TransitionRecoveryError("transition manifest has an invalid operation type")
        operations.append(
            TransitionOperation(
                raw["operation_id"],
                cast(Literal["replace", "delete"], raw["kind"]),
                path,
                cast(OperationCategory, raw["category"]),
                desired,
                raw["mode"],
                _fingerprint_from_data(raw["expected"]),
            )
        )
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    if digest != manifest["plan_digest"]:
        raise TransitionRecoveryError("transition manifest plan digest is invalid")
    plan = TransitionPlan(
        Path(payload["canonical_root"]),
        payload["snapshot_sha"],
        payload["declaration_identity"],
        tuple(operations),
        tuple(payload["conflicts"]),
        tuple(payload["notices"]),
        tuple(payload["validation_exclusions"]),
        digest,
    )
    _validate_plan(plan)
    created_dirs = manifest["created_dirs"]
    assert isinstance(created_dirs, list)
    canonical_dirs = tuple(_validate_relative(item) for item in created_dirs)
    if tuple(created_dirs) != tuple(sorted(set(canonical_dirs))):
        raise TransitionRecoveryError("transition manifest directory metadata is not canonical")
    allowed_dirs = {
        PurePosixPath(*PurePosixPath(operation.path).parts[:index]).as_posix()
        for operation in plan.operations
        for index in range(1, len(PurePosixPath(operation.path).parts))
    }
    if not set(canonical_dirs) <= allowed_dirs:
        raise TransitionRecoveryError("transition manifest directory metadata is outside planned parents")
    return plan


def _pending_journals(state: _TransitionState) -> list[_JournalRef]:
    result: list[_JournalRef] = []
    for name in os.listdir(state.journals_fd):
        if name.startswith(".staging-"):
            continue
        try:
            info = os.stat(name, dir_fd=state.journals_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise TransitionRecoveryError("transition state contains an unsafe journal entry")
        result.append(_JournalRef(state, name))
    return sorted(result, key=lambda item: item.name)


def _terminal_kind(journal: _JournalRef) -> str | None:
    for kind in ("accepted", "rolledback"):
        if journal.name.startswith(f".terminal-{kind}-"):
            return kind
    return None


def _journal_id(journal: _JournalRef) -> str:
    terminal = _terminal_kind(journal)
    if terminal is None:
        return journal.name
    return journal.name.removeprefix(f".terminal-{terminal}-")


def _journal_for_id(state: _TransitionState, journal_id: str) -> _JournalRef:
    journals = _pending_journals(state)
    matches = [journal for journal in journals if journal.name == journal_id or journal.name.endswith(f"-{journal_id}")]
    if len(matches) != 1:
        raise TransitionRecoveryError(f"no unique pending transition journal {journal_id}")
    return matches[0]


def _journal_accepted(journal: _JournalRef) -> bool:
    return any(event["phase"] == "ACCEPTED" for event in _load_events(journal))


def inspect_transition(root: Path) -> TransitionInspection:
    canonical = _canonical_repo(Path(root))
    try:
        with _existing_transition_state(canonical) as state:
            return _inspect_transition_state(state)
    except FileNotFoundError:
        return TransitionInspection(False)


def _inspect_transition_state(state: _TransitionState) -> TransitionInspection:
    journals = _pending_journals(state)
    if not journals:
        return TransitionInspection(False)
    if len(journals) != 1:
        raise TransitionRecoveryError("multiple pending transition journals require manual investigation")
    journal = journals[0]
    terminal = _terminal_kind(journal)
    try:
        manifest = _load_manifest(journal)
    except TransitionRecoveryError:
        if terminal is None:
            raise
        return TransitionInspection(True, _journal_id(journal))
    plan = _plan_from_manifest(manifest)
    events = _load_events(journal)
    accepted_recorded = any(event["phase"] == "ACCEPTED" for event in events)
    applied = {event["operation_id"] for event in events if event["phase"] == "APPLIED"}
    first_pending = next((op.operation_id for op in plan.operations if op.operation_id not in applied), "")
    statuses: dict[str, tuple[OperationStatus, str]] = {}
    for operation in plan.operations:
        if terminal == "accepted" or accepted_recorded:
            statuses[operation.operation_id] = (
                OperationStatus.COMPLETED,
                "accepted; private journal cleanup pending",
            )
        elif terminal == "rolledback":
            statuses[operation.operation_id] = (
                OperationStatus.UNATTEMPTED,
                "rolled back; private journal cleanup pending",
            )
        elif operation.operation_id in applied:
            statuses[operation.operation_id] = (OperationStatus.INDETERMINATE, "recorded applied; recovery pending")
        elif operation.operation_id == first_pending:
            statuses[operation.operation_id] = (OperationStatus.INDETERMINATE, "operation boundary is uncertain")
    result = _result(plan, manifest["journal_id"], statuses, accepted=False)
    return TransitionInspection(True, manifest["journal_id"], plan.digest, result.operations)


def execute_transition(
    plan: TransitionPlan,
    *,
    validate: Validator | None = None,
    fault: FaultHook | None = None,
) -> TransitionResult:
    _validate_plan(plan)
    if plan.conflicts:
        raise TransitionConflictError("; ".join(plan.conflicts))
    validator = _validator_with_internal_check(validate)
    hook = fault or (lambda _phase, _operation: None)
    with _transition_lock(plan.canonical_root, recovery=False) as state:
        pending = _pending_journals(state)
        if pending:
            if len(pending) != 1:
                raise TransitionRecoveryError("multiple pending transition journals require manual investigation")
            manifest = _load_manifest(pending[0])
            if manifest["plan_digest"] != plan.digest:
                raise TransitionRecoveryError(
                    "pending transition belongs to a different plan; explicitly resume or rollback it first"
                )
            terminal = _terminal_kind(pending[0])
            if terminal == "accepted" or _journal_accepted(pending[0]):
                if terminal == "accepted":
                    _remove_terminal_journal(pending[0], hook)
                else:
                    _cleanup_journal(pending[0], hook, terminal="accepted")
                statuses = {
                    operation.operation_id: (OperationStatus.COMPLETED, "accepted") for operation in plan.operations
                }
                return _result(plan, manifest["journal_id"], statuses, accepted=True)
            if terminal == "rolledback":
                raise TransitionRecoveryError("rolled-back terminal journal requires explicit cleanup recovery")
            return _resume_locked(pending[0], plan, validator, hook)
        return _execute_new_locked(state, plan, validator, hook)


def _assert_recovery_states(tree: _SafeTree, plan: TransitionPlan) -> dict[str, FileFingerprint]:
    live: dict[str, FileFingerprint] = {}
    for operation in plan.operations:
        fingerprint = tree.fingerprint(operation.path)
        live[operation.operation_id] = fingerprint
        if fingerprint not in {operation.expected, operation.desired}:
            raise TransitionRecoveryError(
                f"recovery refuses {operation.path}: path matches neither preimage nor desired state"
            )
    return live


def _resume_locked(
    journal: _JournalRef,
    plan: TransitionPlan,
    validate: Validator,
    fault: FaultHook,
) -> TransitionResult:
    _validate_plan(plan)
    manifest = _load_manifest(journal)
    recorded = _plan_from_manifest(manifest)
    if recorded.digest != plan.digest:
        raise TransitionRecoveryError("pending transition belongs to a different plan")
    tree = _SafeTree(plan.canonical_root)
    try:
        live = _assert_recovery_states(tree, plan)
        statuses: dict[str, tuple[OperationStatus, str]] = {}
        for operation in plan.operations:
            for temporary in _authenticated_operation_temps(journal, manifest["journal_id"], operation):
                tree.discard_operation_temp(operation, temporary)
            if live[operation.operation_id] == operation.expected:
                _write_preimage(journal, tree, operation, fault)
                temporary = (
                    _new_operation_temp(manifest["journal_id"], operation) if operation.kind == "replace" else ""
                )
                _append_event(
                    journal,
                    "PREPARED",
                    operation.operation_id,
                    fault,
                    operation,
                    temp_name=temporary,
                )
                _perform_operation(tree, operation, fault, temporary, recovering=True)
            if tree.fingerprint(operation.path) != operation.desired:
                raise TransitionRecoveryError(f"resume could not establish desired state for {operation.path}")
            _append_event(journal, "APPLIED", operation.operation_id, fault, operation)
            statuses[operation.operation_id] = (OperationStatus.COMPLETED, "resumed")
        fault("final_diagnosis", None)
        if not validate(plan.canonical_root, plan):
            raise TransitionRecoveryError("final local convergence diagnosis rejected resumed transition")
        _append_event(journal, "ACCEPTED", "", fault, None)
        _cleanup_journal(journal, fault, terminal="accepted")
        return _result(plan, manifest["journal_id"], statuses, accepted=True)
    finally:
        tree.close()


def resume_transition(
    plan: TransitionPlan,
    journal_id: str,
    *,
    validate: Validator | None = None,
    fault: FaultHook | None = None,
) -> TransitionResult:
    _validate_plan(plan)
    with _transition_lock(plan.canonical_root, recovery=True) as state:
        journal = _journal_for_id(state, journal_id)
        terminal = _terminal_kind(journal)
        if terminal == "rolledback":
            raise TransitionRecoveryError("transition was already rolled back; choose rollback to finalize cleanup")
        if terminal == "accepted":
            try:
                manifest = _load_manifest(journal)
            except TransitionRecoveryError:
                manifest = None
            if manifest is not None:
                recorded = _plan_from_manifest(manifest)
                if recorded.digest != plan.digest:
                    raise TransitionRecoveryError("pending terminal transition belongs to a different plan")
            _remove_terminal_journal(journal, fault or (lambda _phase, _operation: None))
            statuses = {
                operation.operation_id: (OperationStatus.COMPLETED, "accepted") for operation in plan.operations
            }
            return _result(plan, journal_id, statuses, accepted=True)
        if _journal_accepted(journal):
            _cleanup_journal(journal, fault or (lambda _phase, _operation: None), terminal="accepted")
            statuses = {
                operation.operation_id: (OperationStatus.COMPLETED, "accepted") for operation in plan.operations
            }
            return _result(plan, journal_id, statuses, accepted=True)
        return _resume_locked(
            journal,
            plan,
            _validator_with_internal_check(validate),
            fault or (lambda _phase, _operation: None),
        )


def resume_pending_transition(
    root: Path,
    journal_id: str,
    *,
    validate: Validator | None = None,
    fault: FaultHook | None = None,
) -> TransitionResult:
    """Resume a confirmed journal using the digest-bound plan stored in its manifest."""
    canonical = _canonical_repo(Path(root))
    with _transition_lock(canonical, recovery=True) as state:
        journal = _journal_for_id(state, journal_id)
        terminal = _terminal_kind(journal)
        if terminal == "rolledback":
            raise TransitionRecoveryError("transition was already rolled back; choose rollback to finalize cleanup")
        if terminal == "accepted" and not _journal_file_exists(journal, "manifest.json"):
            _remove_terminal_journal(journal, fault or (lambda _phase, _operation: None))
            return TransitionResult(journal_id, "", (), True)
        manifest = _load_manifest(journal)
        if manifest["journal_id"] != journal_id:
            raise TransitionRecoveryError("journal confirmation does not match its manifest")
        plan = _plan_from_manifest(manifest)
        if plan.canonical_root != canonical:
            raise TransitionRecoveryError("journal belongs to a different canonical worktree")
        if terminal == "accepted":
            _remove_terminal_journal(journal, fault or (lambda _phase, _operation: None))
            statuses = {
                operation.operation_id: (OperationStatus.COMPLETED, "accepted") for operation in plan.operations
            }
            return _result(plan, journal_id, statuses, accepted=True)
        if _journal_accepted(journal):
            _cleanup_journal(journal, fault or (lambda _phase, _operation: None), terminal="accepted")
            statuses = {
                operation.operation_id: (OperationStatus.COMPLETED, "accepted") for operation in plan.operations
            }
            return _result(plan, journal_id, statuses, accepted=True)
        return _resume_locked(
            journal,
            plan,
            _validator_with_internal_check(validate),
            fault or (lambda _phase, _operation: None),
        )


def rollback_transition(root: Path, journal_id: str) -> TransitionResult:
    canonical = _canonical_repo(Path(root))
    with _transition_lock(canonical, recovery=True) as state:
        journal = _journal_for_id(state, journal_id)
        terminal = _terminal_kind(journal)
        if terminal == "accepted":
            raise TransitionRecoveryError(
                "accepted transition cannot be rolled back; choose resume to finalize cleanup"
            )
        if terminal is None and _journal_accepted(journal):
            raise TransitionRecoveryError(
                "accepted transition cannot be rolled back; choose resume to finalize cleanup"
            )
        if terminal == "rolledback" and not _journal_file_exists(journal, "manifest.json"):
            _remove_terminal_journal(journal, lambda _phase, _operation: None)
            return TransitionResult(journal_id, "", (), False)
        manifest = _load_manifest(journal)
        if manifest["journal_id"] != journal_id:
            raise TransitionRecoveryError("journal confirmation does not match its manifest")
        plan = _plan_from_manifest(manifest)
        if plan.canonical_root != canonical:
            raise TransitionRecoveryError("journal belongs to a different canonical worktree")
        if terminal == "rolledback":
            _remove_terminal_journal(journal, lambda _phase, _operation: None)
            terminal_statuses = {
                operation.operation_id: (OperationStatus.UNATTEMPTED, "rolled back") for operation in plan.operations
            }
            return _result(plan, journal_id, terminal_statuses, accepted=False)
        tree = _SafeTree(canonical)
        try:
            live = _assert_recovery_states(tree, plan)
            statuses: dict[str, tuple[OperationStatus, str]] = {}
            for operation in reversed(plan.operations):
                temporary_names = _authenticated_operation_temps(journal, manifest["journal_id"], operation)
                for temporary in temporary_names:
                    tree.discard_operation_temp(operation, temporary)
                if live[operation.operation_id] == operation.expected:
                    pass
                elif live[operation.operation_id] == operation.desired:
                    temporary = temporary_names[-1] if operation.kind == "replace" else ""
                    _restore_operation(tree, journal, operation, temporary)
                else:
                    raise TransitionRecoveryError(
                        f"rollback found {operation.path} matching neither preimage nor desired state"
                    )
                if tree.fingerprint(operation.path) != operation.expected:
                    raise TransitionRecoveryError(f"rollback could not restore preimage for {operation.path}")
                statuses[operation.operation_id] = (OperationStatus.UNATTEMPTED, "rolled back")
            tree.remove_empty_dirs(tuple(manifest["created_dirs"]))
            _cleanup_journal(journal, lambda _phase, _operation: None, terminal="rolledback")
            return _result(plan, journal_id, statuses, accepted=False)
        finally:
            tree.close()
