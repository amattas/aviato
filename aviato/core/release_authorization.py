from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .model import deep_freeze, deep_thaw


@dataclass(frozen=True)
class ManagedReleaseCheckpoint:
    repository_id: int
    repository: str
    tag: str
    sha: str
    intended_actor: str
    collector: str
    reviewer: str
    submitter: str
    pin: str
    snapshot_sha: str
    protection_plan_id: str
    protection_receipt_digest: str
    fingerprints: Mapping[str, str]
    workflow_path: str
    workflow_blob_sha: str
    workflow_ref: str
    workflow_run_id: int
    issued_at: int
    expires_at: int
    schema: str = "aviato-managed-release-checkpoint/v1"

    def __post_init__(self) -> None:
        if (
            isinstance(self.repository_id, bool)
            or self.repository_id <= 0
            or "/" not in self.repository
            or self.collector == self.reviewer
        ):
            raise ValueError("checkpoint requires repository identity and a distinct reviewer")
        if self.reviewer in {self.intended_actor, self.submitter}:
            raise ValueError("checkpoint reviewer must differ from actor and workflow submitter")
        if any(not _hex(value, 40) for value in (self.sha, self.snapshot_sha, self.workflow_blob_sha)):
            raise ValueError("checkpoint SHAs must be 40-hex")
        if any(not _hex(value, 64) for value in (self.protection_plan_id, self.protection_receipt_digest)):
            raise ValueError("checkpoint protection evidence must use SHA-256 digests")
        if (
            not self.workflow_ref.startswith("refs/heads/")
            or isinstance(self.workflow_run_id, bool)
            or self.workflow_run_id <= 0
        ):
            raise ValueError("checkpoint requires a concrete default-branch workflow ref/run")
        if (
            isinstance(self.issued_at, bool)
            or not isinstance(self.issued_at, int)
            or isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, int)
            or self.expires_at <= self.issued_at
        ):
            raise ValueError("checkpoint expiry must be after issue time")
        if not self.fingerprints or any(
            not isinstance(key, str) or not key or not _hex(value, 64) for key, value in self.fingerprints.items()
        ):
            raise ValueError("checkpoint fingerprints require named SHA-256 evidence")
        object.__setattr__(self, "fingerprints", deep_freeze(self.fingerprints))

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            {key: deep_thaw(value) for key, value in vars(self).items()},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    @property
    def canonical_bytes(self) -> bytes:
        return self.canonical_json.encode("ascii")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


def _hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str) and len(value) == length and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True)
class RegisteredReviewerKey:
    key_id: str
    reviewer: str
    public_key: bytes
    current: bool
    revoked: bool = False

    def __post_init__(self) -> None:
        if not self.key_id or not self.reviewer or not self.public_key:
            raise ValueError("registered reviewer key requires identity and key bytes")


@dataclass(frozen=True)
class CheckpointVerificationContext:
    repository_id: int
    repository: str
    intended_actor: str
    submitter: str
    reviewer: str
    reviewer_kind: str
    reviewer_database_id: int | None
    reviewer_is_admin: bool
    workflow_path: str
    workflow_blob_sha: str
    workflow_ref: str
    workflow_run_id: int
    source_sha: str
    protection_plan_id: str
    protection_receipt_digest: str
    fingerprints: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fingerprints", deep_freeze(self.fingerprints))


_CHECKPOINT_FIELDS = frozenset(field for field in ManagedReleaseCheckpoint.__dataclass_fields__)
_ENVELOPE_FIELDS = frozenset({"schema", "key_id", "algorithm", "checkpoint", "signature"})
_ENVELOPE_SCHEMA = "aviato-managed-release-checkpoint-envelope/v1"


def _exact_object(value: object, fields: frozenset[str], *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a JSON object")
    actual = set(value)
    if actual != fields:
        raise ValueError(f"{name} keys differ: missing={sorted(fields - actual)!r}, extra={sorted(actual - fields)!r}")
    return value


def _decode_signature(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("checkpoint signature must be non-empty base64url")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("checkpoint signature is not canonical base64url") from exc
    if not decoded or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise ValueError("checkpoint signature is not canonical base64url")
    return decoded


def _checkpoint_from_document(value: object) -> ManagedReleaseCheckpoint:
    document = _exact_object(value, _CHECKPOINT_FIELDS, name="checkpoint")
    fingerprints = document.get("fingerprints")
    if not isinstance(fingerprints, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in fingerprints.items()
    ):
        raise ValueError("checkpoint fingerprints must be a string mapping")
    # Dataclass validation rejects bool-as-int and all malformed identity/digest values.
    try:
        return ManagedReleaseCheckpoint(**document)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid checkpoint document: {exc}") from exc


def verify_checkpoint_envelope(
    raw: bytes,
    *,
    context: CheckpointVerificationContext,
    resolve_key: Callable[[str], RegisteredReviewerKey | None],
    verify_signature: Callable[[bytes, bytes, bytes], bool],
    now: int,
) -> ManagedReleaseCheckpoint:
    """Verify canonical signature bytes and every fresh platform binding, fail closed."""

    if not raw or len(raw) > 65_536:
        raise ValueError("checkpoint envelope is empty or too large")
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("checkpoint envelope is not valid JSON") from exc
    envelope = _exact_object(parsed, _ENVELOPE_FIELDS, name="checkpoint envelope")
    if raw != json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"):
        raise ValueError("checkpoint envelope must use exact canonical JSON bytes")
    if envelope["schema"] != _ENVELOPE_SCHEMA or envelope["algorithm"] != "ssh-ed25519":
        raise ValueError("unsupported checkpoint envelope schema or signature algorithm")
    key_id = envelope["key_id"]
    if not isinstance(key_id, str) or not key_id:
        raise ValueError("checkpoint envelope key_id is invalid")
    checkpoint = _checkpoint_from_document(envelope["checkpoint"])
    key = resolve_key(key_id)
    if key is None or key.key_id != key_id or not key.current or key.revoked or key.reviewer != checkpoint.reviewer:
        raise ValueError("checkpoint reviewer key is absent, revoked, replaced, or mismatched")
    signature = _decode_signature(envelope["signature"])
    if verify_signature(key.public_key, checkpoint.canonical_bytes, signature) is not True:
        raise ValueError("checkpoint signature verification failed")
    if isinstance(now, bool) or not isinstance(now, int) or not checkpoint.issued_at <= now < checkpoint.expires_at:
        raise ValueError("checkpoint is not currently fresh")
    expected = {
        "repository_id": context.repository_id,
        "repository": context.repository,
        "intended_actor": context.intended_actor,
        "submitter": context.submitter,
        "reviewer": context.reviewer,
        "workflow_path": context.workflow_path,
        "workflow_blob_sha": context.workflow_blob_sha,
        "workflow_ref": context.workflow_ref,
        "workflow_run_id": context.workflow_run_id,
        "sha": context.source_sha,
        "protection_plan_id": context.protection_plan_id,
        "protection_receipt_digest": context.protection_receipt_digest,
        "fingerprints": context.fingerprints,
    }
    mismatched = [name for name, value in expected.items() if getattr(checkpoint, name) != value]
    if mismatched:
        raise ValueError(f"checkpoint live evidence mismatch: {mismatched!r}")
    if (
        context.reviewer_kind != "user"
        or context.reviewer_database_id is None
        or context.reviewer_database_id <= 0
        or not context.reviewer_is_admin
        or checkpoint.reviewer in {checkpoint.intended_actor, checkpoint.submitter, checkpoint.collector}
    ):
        raise ValueError("checkpoint reviewer is not a distinct current concrete admin user")
    return checkpoint


def collect_checkpoint(checkpoint: ManagedReleaseCheckpoint, *, credential_present: bool) -> bytes:
    if not credential_present:
        raise ValueError("checkpoint collection requires the operator credential")
    return checkpoint.canonical_bytes


def review_sign(
    unsigned: bytes,
    *,
    reviewer: str,
    collector: str,
    signer: Callable[[bytes], bytes],
) -> bytes:
    if reviewer == collector:
        raise ValueError("checkpoint reviewer must be distinct from collector")
    return signer(unsigned)


def review_sign_envelope(
    unsigned: bytes,
    *,
    reviewer: str,
    collector: str,
    key_id: str,
    signer: Callable[[bytes], bytes],
) -> bytes:
    """Create the one canonical envelope a distinct reviewer actually signed."""

    try:
        document = json.loads(unsigned)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("unsigned checkpoint is not valid JSON") from exc
    checkpoint = _checkpoint_from_document(document)
    if unsigned != checkpoint.canonical_bytes:
        raise ValueError("unsigned checkpoint must use exact canonical bytes")
    if checkpoint.reviewer != reviewer or checkpoint.collector != collector or reviewer == collector:
        raise ValueError("checkpoint reviewer/collector binding is not distinct and exact")
    if not key_id:
        raise ValueError("checkpoint review requires a registered key id")
    signature = review_sign(unsigned, reviewer=reviewer, collector=collector, signer=signer)
    if not signature:
        raise ValueError("checkpoint signer returned an empty signature")
    envelope = {
        "schema": _ENVELOPE_SCHEMA,
        "key_id": key_id,
        "algorithm": "ssh-ed25519",
        "checkpoint": document,
        "signature": base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def persist_checkpoint_envelope(
    envelope: bytes,
    *,
    checkpoint: ManagedReleaseCheckpoint,
    persist: Callable[[bytes], object],
) -> str:
    """Persist exactly the verified signed bytes; never reconstruct or edit them."""

    parsed = json.loads(envelope)
    exact = _exact_object(parsed, _ENVELOPE_FIELDS, name="checkpoint envelope")
    if envelope != json.dumps(exact, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"):
        raise ValueError("checkpoint envelope persistence requires canonical bytes")
    if exact.get("checkpoint") != json.loads(checkpoint.canonical_json):
        raise ValueError("verified checkpoint does not match the envelope being persisted")
    persist(envelope)
    return hashlib.sha256(envelope).hexdigest()


def promotion_ready(
    checkpoint: ManagedReleaseCheckpoint,
    *,
    actor: str,
    tag: str,
    sha: str,
    digest: str,
    now: int,
) -> bool:
    return (
        checkpoint.intended_actor == actor
        and checkpoint.reviewer != actor
        and checkpoint.tag == tag
        and checkpoint.sha == sha
        and checkpoint.digest == digest
        and checkpoint.issued_at <= now < checkpoint.expires_at
    )


def reviewer_ready(*, kind: str, concrete_user_id: int | None, membership_verified: bool) -> bool:
    return kind == "user" and concrete_user_id is not None and membership_verified


def guard_descriptor_ready(descriptor: object | None) -> bool:
    if not isinstance(descriptor, Mapping):
        return False
    return all(descriptor.get(key) for key in ("path", "blob_sha", "schema"))
