from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal

import yaml

from aviato.repos import git_candidate_paths, git_root

from .errors import InventoryError, PathConfinementError
from .marker import (
    MarkerInfo,
    canonical_input_hash,
    content_hash,
    marker_line_from_text,
    marker_token_present,
    parse_marker_from_text,
    render_marker,
    strip_marker_from_text,
)
from .pathguard import confined_target
from .version import is_known_version_pin

INVENTORY_PATH = ".github/aviato.managed.yml"
INVENTORY_SCHEMA_VERSION = 1
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_TOP_LEVEL_BUILD_ROOTS = frozenset({"build", "dist", "_wheelout", ".tox", ".venv", "node_modules"})


def _path_identity(value: str) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in PurePosixPath(value).parts)


def _case_equivalent_path(left: str, right: str) -> bool:
    return _path_identity(left) == _path_identity(right)


def _closed_mapping(value: object, *, fields: frozenset[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be a string-keyed mapping")
    unknown = set(value) - fields
    if unknown:
        raise ValueError(f"{context} has unknown fields: {', '.join(sorted(unknown))}")
    missing = fields - set(value)
    if missing:
        raise ValueError(f"{context} is missing fields: {', '.join(sorted(missing))}")
    return value


def _nonempty(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a nonempty string")
    return value


def _hex64(value: object, *, context: str) -> str:
    text = _nonempty(value, context=context)
    if _HEX_64.fullmatch(text) is None:
        raise ValueError(f"{context} must be a lowercase SHA-256 hex digest")
    return text


def _path(value: object, *, context: str) -> str:
    text = _nonempty(value, context=context)
    if "\0" in text or "\\" in text:
        raise ValueError(f"{context} is not a canonical repository-relative path")
    parsed = PurePosixPath(text)
    if parsed.is_absolute() or text != parsed.as_posix() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError(f"{context} is not a canonical repository-relative path")
    folded_parts = tuple(part.casefold() for part in parsed.parts)
    if folded_parts[0] in _TOP_LEVEL_BUILD_ROOTS or any(part in {".git", ".worktrees"} for part in folded_parts):
        raise ValueError(f"{context} targets a protected repository root")
    return text


def _string_tuple(value: object, *, context: str, paths: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    result = tuple((_path(item, context=context) if paths else _nonempty(item, context=context)) for item in value)
    identities: tuple[object, ...] = tuple(_path_identity(item) for item in result) if paths else result
    if len(set(identities)) != len(result):
        raise ValueError(f"{context} contains duplicates")
    return result


@dataclass(frozen=True)
class InventoryEntry:
    artifact_id: str
    pipeline_owners: tuple[str, ...]
    marker_hash: str
    body_hash: str
    input_hash: str
    legacy_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.artifact_id, context="artifact_id")
        if not isinstance(self.pipeline_owners, tuple) or any(
            not isinstance(owner, str) or not owner for owner in self.pipeline_owners
        ):
            raise ValueError("pipeline_owners must be nonempty strings")
        if len(set(self.pipeline_owners)) != len(self.pipeline_owners):
            raise ValueError("pipeline_owners contains duplicates")
        _hex64(self.marker_hash, context="marker_hash")
        _hex64(self.body_hash, context="body_hash")
        _hex64(self.input_hash, context="input_hash")
        for alias in self.legacy_aliases:
            _path(alias, context="legacy_alias")
            if _case_equivalent_path(alias, INVENTORY_PATH):
                raise ValueError("the managed inventory cannot list itself as a legacy alias")
        if len({_path_identity(alias) for alias in self.legacy_aliases}) != len(self.legacy_aliases):
            raise ValueError("legacy_aliases contains duplicates")


@dataclass(frozen=True)
class OwnedRulesetEntry:
    name: str
    target: str
    snapshot_commit: str
    payload_fingerprint: str

    def __post_init__(self) -> None:
        _nonempty(self.name, context="ruleset name")
        _nonempty(self.target, context="ruleset target")
        if not isinstance(self.snapshot_commit, str) or _COMMIT.fullmatch(self.snapshot_commit) is None:
            raise ValueError("ruleset snapshot_commit must be a lowercase Git object ID")
        _hex64(self.payload_fingerprint, context="ruleset payload_fingerprint")


@dataclass(frozen=True)
class ManagedInventory:
    schema_version: int
    profile: str
    profile_identity: str
    pin: str
    snapshot_commit: str
    entries: Mapping[str, InventoryEntry] = field(default_factory=dict)
    owned_rulesets: tuple[OwnedRulesetEntry, ...] = ()

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != INVENTORY_SCHEMA_VERSION:
            raise ValueError(f"unsupported managed inventory schema {self.schema_version!r}")
        _nonempty(self.profile, context="profile")
        _nonempty(self.profile_identity, context="profile_identity")
        if not isinstance(self.pin, str) or not is_known_version_pin(self.pin):
            raise ValueError("pin must be a recognized version pin")
        if not isinstance(self.snapshot_commit, str) or _COMMIT.fullmatch(self.snapshot_commit) is None:
            raise ValueError("snapshot_commit must be a lowercase Git object ID")
        if not isinstance(self.entries, Mapping):
            raise ValueError("entries must be a mapping")
        identities: set[str] = set()
        path_identities: set[tuple[str, ...]] = set()
        for path, entry in self.entries.items():
            canonical = _path(path, context="inventory entry path")
            if _case_equivalent_path(canonical, INVENTORY_PATH):
                raise ValueError("the managed inventory cannot list itself")
            path_identity = _path_identity(canonical)
            if path_identity in path_identities:
                raise ValueError(f"case-equivalent inventory entry path collision at {path!r}")
            path_identities.add(path_identity)
            if not isinstance(entry, InventoryEntry):
                raise ValueError(f"inventory entry {path!r} has the wrong type")
            if entry.artifact_id in identities:
                raise ValueError(f"duplicate artifact identity {entry.artifact_id!r}")
            identities.add(entry.artifact_id)
        for entry in self.entries.values():
            for alias in entry.legacy_aliases:
                if _path_identity(alias) in path_identities:
                    raise ValueError(f"legacy alias {alias!r} collides with a current inventory entry path")
        object.__setattr__(self, "entries", MappingProxyType(dict(self.entries)))
        if not isinstance(self.owned_rulesets, tuple) or any(
            not isinstance(item, OwnedRulesetEntry) for item in self.owned_rulesets
        ):
            raise ValueError("owned_rulesets must contain OwnedRulesetEntry values")
        rule_identities = [(rule.name, rule.target) for rule in self.owned_rulesets]
        if len(set(rule_identities)) != len(rule_identities):
            raise ValueError("owned_rulesets contains duplicate stable identities")


def owned_rulesets_by_identity(inventory: ManagedInventory | None) -> Mapping[tuple[str, str], OwnedRulesetEntry]:
    """Return the fail-closed ownership index used by ruleset retirement plans."""

    if inventory is None:
        return MappingProxyType({})
    return MappingProxyType({(entry.name, entry.target): entry for entry in inventory.owned_rulesets})


InventoryReadStatus = Literal["valid", "missing", "invalid"]
MarkerArtifactStatus = Literal["valid", "malformed", "unreadable", "symlink", "nonfile"]


@dataclass(frozen=True)
class InventoryRead:
    status: InventoryReadStatus
    inventory: ManagedInventory | None = None
    reason: str | None = None


@dataclass(frozen=True)
class MarkerArtifact:
    path: str
    status: MarkerArtifactStatus
    marker: MarkerInfo | None = None
    live_body_hash: str | None = None
    marker_line_hash: str | None = None


@dataclass(frozen=True)
class InventoryReconciliation:
    expected: tuple[str, ...]
    obsolete_clean: tuple[str, ...]
    obsolete_missing: tuple[str, ...]
    obsolete_blocked: dict[str, str]
    legacy_adoptable: dict[str, str]
    ambiguous: dict[str, tuple[str, ...]]
    next_inventory: ManagedInventory
    inventory_status: InventoryReadStatus


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: yaml.SafeLoader, mapping_node: yaml.nodes.MappingNode, deep: bool = False) -> Any:
    result: dict[Any, Any] = {}
    for key_node, value_node in mapping_node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate inventory key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _entry_from_data(value: object, *, context: str) -> InventoryEntry:
    data = _closed_mapping(
        value,
        fields=frozenset(
            {"artifact_id", "pipeline_owners", "marker_hash", "body_hash", "input_hash", "legacy_aliases"}
        ),
        context=context,
    )
    return InventoryEntry(
        artifact_id=_nonempty(data["artifact_id"], context=f"{context}.artifact_id"),
        pipeline_owners=_string_tuple(data["pipeline_owners"], context=f"{context}.pipeline_owners"),
        marker_hash=_hex64(data["marker_hash"], context=f"{context}.marker_hash"),
        body_hash=_hex64(data["body_hash"], context=f"{context}.body_hash"),
        input_hash=_hex64(data["input_hash"], context=f"{context}.input_hash"),
        legacy_aliases=_string_tuple(data["legacy_aliases"], context=f"{context}.legacy_aliases", paths=True),
    )


def _ruleset_from_data(value: object, *, context: str) -> OwnedRulesetEntry:
    data = _closed_mapping(
        value,
        fields=frozenset({"name", "target", "snapshot_commit", "payload_fingerprint"}),
        context=context,
    )
    return OwnedRulesetEntry(
        name=_nonempty(data["name"], context=f"{context}.name"),
        target=_nonempty(data["target"], context=f"{context}.target"),
        snapshot_commit=_nonempty(data["snapshot_commit"], context=f"{context}.snapshot_commit"),
        payload_fingerprint=_hex64(data["payload_fingerprint"], context=f"{context}.payload_fingerprint"),
    )


def _inventory_from_body(body: str) -> ManagedInventory:
    try:
        loaded = yaml.load(body, Loader=_UniqueSafeLoader)
    except (yaml.YAMLError, ValueError) as exc:
        raise ValueError(f"invalid managed inventory YAML: {exc}") from exc
    data = _closed_mapping(
        loaded,
        fields=frozenset(
            {
                "schema_version",
                "profile",
                "profile_identity",
                "pin",
                "snapshot_commit",
                "entries",
                "owned_remote_resources",
            }
        ),
        context="managed inventory",
    )
    entries_data = data["entries"]
    if not isinstance(entries_data, dict) or any(not isinstance(path, str) for path in entries_data):
        raise ValueError("managed inventory entries must be a string-keyed mapping")
    entries = {
        _path(path, context="inventory entry path"): _entry_from_data(value, context=f"entries[{path!r}]")
        for path, value in entries_data.items()
    }
    remote = _closed_mapping(
        data["owned_remote_resources"], fields=frozenset({"rulesets"}), context="owned_remote_resources"
    )
    raw_rulesets = remote["rulesets"]
    if not isinstance(raw_rulesets, list):
        raise ValueError("owned_remote_resources.rulesets must be a list")
    return ManagedInventory(
        schema_version=data["schema_version"],
        profile=_nonempty(data["profile"], context="profile"),
        profile_identity=_nonempty(data["profile_identity"], context="profile_identity"),
        pin=_nonempty(data["pin"], context="pin"),
        snapshot_commit=_nonempty(data["snapshot_commit"], context="snapshot_commit"),
        entries=entries,
        owned_rulesets=tuple(
            _ruleset_from_data(item, context=f"owned_remote_resources.rulesets[{index}]")
            for index, item in enumerate(raw_rulesets)
        ),
    )


def _inventory_data(inventory: ManagedInventory) -> dict[str, Any]:
    return {
        "schema_version": inventory.schema_version,
        "profile": inventory.profile,
        "profile_identity": inventory.profile_identity,
        "pin": inventory.pin,
        "snapshot_commit": inventory.snapshot_commit,
        "entries": {
            path: {
                "artifact_id": entry.artifact_id,
                "pipeline_owners": sorted(entry.pipeline_owners),
                "marker_hash": entry.marker_hash,
                "body_hash": entry.body_hash,
                "input_hash": entry.input_hash,
                "legacy_aliases": sorted(entry.legacy_aliases),
            }
            for path, entry in sorted(inventory.entries.items())
        },
        "owned_remote_resources": {
            "rulesets": [
                {
                    "name": rule.name,
                    "target": rule.target,
                    "snapshot_commit": rule.snapshot_commit,
                    "payload_fingerprint": rule.payload_fingerprint,
                }
                for rule in sorted(inventory.owned_rulesets, key=lambda item: (item.name, item.target))
            ]
        },
    }


def _inventory_input_hash(inventory: ManagedInventory) -> str:
    return canonical_input_hash(
        {
            "profile_identity": inventory.profile_identity,
            "pin": inventory.pin,
            "snapshot_commit": inventory.snapshot_commit,
        }
    )


def render_managed_inventory(inventory: ManagedInventory) -> str:
    """Render deterministic schema-v1 YAML with a normal managed marker."""
    body = yaml.safe_dump(_inventory_data(inventory), sort_keys=False, default_flow_style=False)
    marker = render_marker(
        profile=inventory.profile,
        version=inventory.pin,
        body=body,
        comment="#",
        input_hash=_inventory_input_hash(inventory),
    )
    return f"{marker}\n{body}"


def load_managed_inventory(root: Path) -> InventoryRead:
    """Load and independently validate the inventory marker, body, and schema."""
    try:
        target = confined_target(root, INVENTORY_PATH, operation="read managed inventory")
    except PathConfinementError as exc:
        return InventoryRead("invalid", reason=str(exc))
    if not target.exists():
        return InventoryRead("missing")
    if target.is_symlink() or not target.is_file():
        return InventoryRead("invalid", reason="managed inventory is not a regular file")
    try:
        target = confined_target(root, INVENTORY_PATH, operation="read managed inventory")
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, PathConfinementError) as exc:
        return InventoryRead("invalid", reason=f"managed inventory is unreadable: {exc}")
    marker = parse_marker_from_text(text)
    line = marker_line_from_text(text)
    if marker is None or line is None:
        return InventoryRead("invalid", reason="managed inventory marker is missing or malformed")
    body = strip_marker_from_text(text)
    try:
        inventory = _inventory_from_body(body)
    except (TypeError, ValueError) as exc:
        return InventoryRead("invalid", reason=str(exc))
    try:
        _validate_inventory_root_paths(Path(root).resolve(), inventory)
    except InventoryError as exc:
        return InventoryRead("invalid", reason=str(exc))
    if marker.profile != inventory.profile:
        return InventoryRead("invalid", reason="managed inventory marker profile does not match its body")
    if marker.version != inventory.pin or not is_known_version_pin(marker.version):
        return InventoryRead("invalid", reason="managed inventory marker pin does not match its body")
    if marker.hash != content_hash(body):
        return InventoryRead("invalid", reason="managed inventory body does not match its marker hash")
    if marker.input_hash != _inventory_input_hash(inventory):
        return InventoryRead("invalid", reason="managed inventory marker input hash is stale")
    return InventoryRead("valid", inventory=inventory)


def _nested_repository_parent(root: Path, relative: str) -> Path | None:
    parent = root
    for part in PurePosixPath(relative).parts[:-1]:
        parent /= part
        if parent.is_symlink():
            return None
        if (parent / ".git").exists():
            return parent
    return None


def _validate_inventory_root_paths(root: Path, inventory: ManagedInventory) -> None:
    for path, entry in inventory.entries.items():
        nested = _nested_repository_parent(root, path)
        if nested is not None:
            raise InventoryError(f"inventory path {path!r} enters nested repository or worktree {nested}")
        for alias in entry.legacy_aliases:
            nested_alias = _nested_repository_parent(root, alias)
            if nested_alias is not None:
                raise InventoryError(f"legacy alias {alias!r} enters nested repository or worktree {nested_alias}")


def _excluded_candidate(root: Path, relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    folded_parts = tuple(part.casefold() for part in parts)
    if _case_equivalent_path(relative, INVENTORY_PATH) or not parts:
        return True
    # An embedded repository is reported by the outer repository as a directory
    # entry with a trailing slash. It is a separate marker universe.
    if relative.endswith("/") and (root.joinpath(*parts) / ".git").exists():
        return True
    if folded_parts[0] in _TOP_LEVEL_BUILD_ROOTS or any(part in {".git", ".worktrees"} for part in folded_parts):
        return True
    return _nested_repository_parent(root, relative) is not None


def _inspect_candidate(root: Path, relative: str) -> MarkerArtifact | None:
    try:
        canonical = _path(relative, context="Git candidate path")
    except ValueError as exc:
        raise InventoryError(f"unsafe path returned by Git: {relative!r}: {exc}") from exc
    lexical_target = root.joinpath(*PurePosixPath(canonical).parts)
    # A symlink cannot prove it contains an in-repository marker, so it is not a
    # universe member by itself. A prior inventory path is inspected separately
    # and will classify the same substitution as blocking.
    if lexical_target.is_symlink():
        return None
    try:
        target = confined_target(root, canonical, operation="scan managed marker universe")
    except PathConfinementError:
        return None
    if not target.is_file():
        return None
    try:
        raw = target.read_bytes()
    except OSError:
        return MarkerArtifact(canonical, "unreadable")
    if not marker_token_present(raw):
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return MarkerArtifact(canonical, "unreadable")
    marker = parse_marker_from_text(text)
    line = marker_line_from_text(text)
    if marker is None or line is None:
        return MarkerArtifact(canonical, "malformed")
    return MarkerArtifact(
        canonical,
        "valid",
        marker=marker,
        live_body_hash=content_hash(strip_marker_from_text(text)),
        marker_line_hash=content_hash(line),
    )


def scan_marker_universe(root: Path) -> dict[str, MarkerArtifact]:
    """Scan all tracked and untracked nonignored Git files for managed markers."""
    canonical_root = Path(root).resolve()
    discovered_root = git_root(canonical_root)
    if discovered_root is None or discovered_root != canonical_root:
        raise InventoryError(f"marker-universe scan requires the canonical Git worktree root: {canonical_root}")
    universe: dict[str, MarkerArtifact] = {}
    for relative in git_candidate_paths(canonical_root):
        if _excluded_candidate(canonical_root, relative):
            continue
        artifact = _inspect_candidate(canonical_root, relative)
        if artifact is not None:
            universe[relative] = artifact
    return dict(sorted(universe.items()))


def _inspect_prior_path(root: Path, relative: str) -> MarkerArtifact | None:
    try:
        target = confined_target(root, relative, operation="inspect obsolete managed artifact")
    except PathConfinementError:
        return MarkerArtifact(relative, "symlink")
    if not target.exists() and not target.is_symlink():
        return None
    if target.is_symlink():
        return MarkerArtifact(relative, "symlink")
    if not target.is_file():
        return MarkerArtifact(relative, "nonfile")
    try:
        raw = target.read_bytes()
    except OSError:
        return MarkerArtifact(relative, "unreadable")
    if not marker_token_present(raw):
        return MarkerArtifact(relative, "malformed")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return MarkerArtifact(relative, "unreadable")
    marker = parse_marker_from_text(text)
    line = marker_line_from_text(text)
    if marker is None or line is None:
        return MarkerArtifact(relative, "malformed")
    return MarkerArtifact(
        relative,
        "valid",
        marker=marker,
        live_body_hash=content_hash(strip_marker_from_text(text)),
        marker_line_hash=content_hash(line),
    )


def _retirement_block_reason(
    artifact: MarkerArtifact,
    prior_entry: InventoryEntry,
    *,
    current_profile: str,
    source_profile: str | None,
) -> str | None:
    if artifact.status != "valid" or artifact.marker is None:
        return f"obsolete artifact is {artifact.status}"
    marker = artifact.marker
    if marker.profile not in {current_profile, source_profile}:
        return f"obsolete marker belongs to foreign profile {marker.profile!r}"
    if not is_known_version_pin(marker.version):
        return f"obsolete marker records unknown version {marker.version!r}"
    if marker.input_hash != prior_entry.input_hash:
        return "obsolete marker input hash does not match the prior inventory"
    if marker.hash != prior_entry.body_hash or artifact.live_body_hash != marker.hash:
        return "obsolete body is modified or does not match the prior inventory"
    if artifact.marker_line_hash != prior_entry.marker_hash:
        return "obsolete marker does not match the prior inventory"
    return None


def reconcile_managed_inventory(
    root: Path,
    desired: ManagedInventory,
    *,
    prior: InventoryRead | None = None,
    source_profile: str | None = None,
    seed_once_paths: set[str] | frozenset[str] = frozenset(),
) -> InventoryReconciliation:
    """Reconcile desired state, prior index, and the live marker universe."""
    canonical_root = Path(root).resolve()
    _validate_inventory_root_paths(canonical_root, desired)
    for path in desired.entries:
        confined_target(canonical_root, path, operation="validate desired inventory path")
    for path in seed_once_paths:
        _path(path, context="seed-once path")
        confined_target(canonical_root, path, operation="validate seed-once path")

    prior_read = prior or load_managed_inventory(canonical_root)
    prior_inventory = prior_read.inventory if prior_read.status == "valid" else None
    if prior_inventory is not None:
        _validate_inventory_root_paths(canonical_root, prior_inventory)
    prior_entries = prior_inventory.entries if prior_inventory is not None else {}
    desired_by_path_identity = {_path_identity(path): entry for path, entry in desired.entries.items()}
    desired_path_identities = set(desired_by_path_identity)
    prior_path_identities = {_path_identity(path) for path in prior_entries}
    seed_path_identities = {_path_identity(path) for path in seed_once_paths}
    universe = scan_marker_universe(canonical_root)
    obsolete_clean: list[str] = []
    obsolete_missing: list[str] = []
    blocked: dict[str, str] = {}
    adoptable: dict[str, str] = {}
    ambiguous: dict[str, tuple[str, ...]] = {}
    universe_spellings: dict[tuple[str, ...], list[str]] = {}
    for path in universe:
        universe_spellings.setdefault(_path_identity(path), []).append(path)
    conflicting_universe_identities: set[tuple[str, ...]] = set()
    for identity, spellings in sorted(universe_spellings.items()):
        if len(spellings) < 2:
            continue
        ordered = sorted(spellings)
        blocked[ordered[0]] = f"case-equivalent Git paths collide: {', '.join(ordered)}"
        conflicting_universe_identities.add(identity)

    for path, entry in sorted(prior_entries.items()):
        path_identity = _path_identity(path)
        if path_identity in desired_path_identities:
            desired_entry = desired_by_path_identity[path_identity]
            if desired_entry.artifact_id != entry.artifact_id:
                blocked[path] = "case-equivalent path changed stable artifact identity"
            continue
        if path_identity in seed_path_identities:
            blocked[path] = "seed-once artifact is operator-owned and cannot be retired"
            continue
        artifact = _inspect_prior_path(canonical_root, path)
        if artifact is None:
            obsolete_missing.append(path)
            continue
        reason = _retirement_block_reason(
            artifact,
            entry,
            current_profile=desired.profile,
            source_profile=source_profile,
        )
        if reason is None:
            obsolete_clean.append(path)
        else:
            blocked[path] = reason

    alias_owners: dict[tuple[str, ...], set[str]] = {}
    alias_spellings: dict[tuple[str, ...], set[str]] = {}
    for entry in desired.entries.values():
        for alias in entry.legacy_aliases:
            identity = _path_identity(alias)
            alias_owners.setdefault(identity, set()).add(entry.artifact_id)
            alias_spellings.setdefault(identity, set()).add(alias)

    known_path_identities = desired_path_identities | prior_path_identities
    inspected_alias_identities: set[tuple[str, ...]] = set()
    for identity in sorted(alias_owners):
        if identity in known_path_identities:
            continue
        path = sorted(alias_spellings[identity])[0]
        artifact = None
        for spelling in sorted(alias_spellings[identity]):
            inspected = _inspect_prior_path(canonical_root, spelling)
            if inspected is not None:
                path = spelling
                artifact = inspected
                break
        if artifact is None:
            continue
        inspected_alias_identities.add(identity)
        candidates = tuple(sorted(alias_owners[identity]))
        if identity in seed_path_identities:
            blocked[path] = "seed-once artifact is operator-owned and cannot be adopted or retired"
            continue
        if len(candidates) > 1:
            ambiguous[path] = candidates
            blocked[path] = "legacy path maps to multiple stable artifact identities"
            continue
        marker = artifact.marker
        if (
            artifact.status == "valid"
            and marker is not None
            and marker.profile in {desired.profile, source_profile}
            and is_known_version_pin(marker.version)
            and artifact.live_body_hash == marker.hash
        ):
            adoptable[path] = candidates[0]
            continue
        blocked[path] = f"legacy path is {artifact.status}, not a clean recognized managed artifact"

    for path, artifact in universe.items():
        identity = _path_identity(path)
        if identity in conflicting_universe_identities:
            continue
        if identity in known_path_identities or identity in inspected_alias_identities:
            continue
        if identity in seed_path_identities:
            # Seed-once files are explicitly operator-owned and may mention the
            # marker token in documentation or examples. Their sidecar identity
            # excludes them from managed-universe adoption/retirement.
            continue
        candidates = tuple(sorted(alias_owners.get(identity, ())))
        if candidates:
            if len(candidates) > 1:
                ambiguous[path] = candidates
                blocked[path] = "legacy path maps to multiple stable artifact identities"
                continue
            marker = artifact.marker
            if (
                artifact.status == "valid"
                and marker is not None
                and marker.profile in {desired.profile, source_profile}
                and is_known_version_pin(marker.version)
                and artifact.live_body_hash == marker.hash
            ):
                adoptable[path] = candidates[0]
                continue
            blocked[path] = f"legacy path is {artifact.status}, not a clean recognized managed artifact"
            continue
        blocked[path] = "marker universe contains a managed path the inventory omits"

    return InventoryReconciliation(
        expected=tuple(sorted(desired.entries)),
        obsolete_clean=tuple(obsolete_clean),
        obsolete_missing=tuple(obsolete_missing),
        obsolete_blocked=dict(sorted(blocked.items())),
        legacy_adoptable=dict(sorted(adoptable.items())),
        ambiguous=dict(sorted(ambiguous.items())),
        next_inventory=desired,
        inventory_status=prior_read.status,
    )
