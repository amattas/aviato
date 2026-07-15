from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..authority_verifier import AUTHORITY_SNAPSHOT_SCHEMA
from .model import deep_freeze, deep_thaw
from .protection import authority_snapshot_digest

MAX_CHECKPOINT_TTL_SECONDS = 15 * 60
MAX_CHECKPOINT_CLOCK_SKEW_SECONDS = 30


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
    authority_snapshot: Mapping[str, Any]
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
        if self.expires_at - self.issued_at > MAX_CHECKPOINT_TTL_SECONDS:
            raise ValueError(f"checkpoint TTL exceeds {MAX_CHECKPOINT_TTL_SECONDS} seconds")
        if self.authority_snapshot.get("schema") != AUTHORITY_SNAPSHOT_SCHEMA:
            raise ValueError("checkpoint requires one canonical authority snapshot")
        authority_snapshot_digest(self.authority_snapshot)
        object.__setattr__(self, "authority_snapshot", deep_freeze(self.authority_snapshot))

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
    authority_snapshot: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.authority_snapshot.get("schema") != AUTHORITY_SNAPSHOT_SCHEMA:
            raise ValueError("verification context requires one canonical authority snapshot")
        object.__setattr__(self, "authority_snapshot", deep_freeze(self.authority_snapshot))


@dataclass(frozen=True)
class CheckpointIntakeRun:
    run_id: int
    workflow_path: str
    workflow_blob_sha: str
    workflow_ref: str
    head_sha: str
    tag: str
    envelope_digest: str
    expires_at: int
    conclusion: str
    attestation_verified: bool

    def __post_init__(self) -> None:
        if isinstance(self.run_id, bool) or self.run_id <= 0:
            raise ValueError("checkpoint intake run requires a positive run id")
        if not self.workflow_path.startswith(".github/workflows/"):
            raise ValueError("checkpoint intake run requires a trusted workflow path")
        if not self.workflow_ref.startswith("refs/heads/"):
            raise ValueError("checkpoint intake run requires a concrete branch ref")
        if not _hex(self.workflow_blob_sha, 40) or not _hex(self.head_sha, 40):
            raise ValueError("checkpoint intake run requires immutable workflow/source SHAs")
        if not _hex(self.envelope_digest, 64):
            raise ValueError("checkpoint intake run requires an envelope digest")


def select_checkpoint_intake_run(
    runs: list[CheckpointIntakeRun] | tuple[CheckpointIntakeRun, ...],
    *,
    workflow_path: str,
    workflow_blob_sha: str,
    workflow_ref: str,
    head_sha: str,
    tag: str,
    envelope_digest: str,
    now: int,
) -> CheckpointIntakeRun:
    """Select one independently attested intake run; caller-provided IDs are not authority."""

    matching = [
        run
        for run in runs
        if run.workflow_path == workflow_path
        and run.workflow_blob_sha == workflow_blob_sha
        and run.workflow_ref == workflow_ref
        and run.head_sha == head_sha
        and run.tag == tag
        and run.envelope_digest == envelope_digest
        and run.conclusion == "success"
        and run.attestation_verified
        and now < run.expires_at
    ]
    if len(matching) != 1:
        raise ValueError("release authorization requires exactly one trusted, attested, unexpired checkpoint run")
    return matching[0]


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
    authority_snapshot = document.get("authority_snapshot")
    if not isinstance(authority_snapshot, dict):
        raise ValueError("checkpoint authority_snapshot must be an object")
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
    if isinstance(now, bool) or not isinstance(now, int):
        raise ValueError("checkpoint verification time must be an integer epoch")
    if checkpoint.issued_at > now + MAX_CHECKPOINT_CLOCK_SKEW_SECONDS:
        raise ValueError("checkpoint issue time exceeds bounded clock skew")
    if now >= checkpoint.expires_at:
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
        "authority_snapshot": context.authority_snapshot,
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


def require_final_mutation_authority(
    *,
    checkpoint: object,
    current_snapshot: Mapping[str, Any],
    now: int,
    reviewer_is_admin: bool,
    key_current: bool,
    signature_verified: bool,
    attestation_verified: bool,
) -> None:
    """Fail closed immediately before any privileged release mutation."""

    issued_at = getattr(checkpoint, "issued_at", None)
    expires_at = getattr(checkpoint, "expires_at", None)
    expected_snapshot = getattr(checkpoint, "authority_snapshot", None)
    if (
        type(now) is not int
        or type(issued_at) is not int
        or type(expires_at) is not int
        or issued_at > now + MAX_CHECKPOINT_CLOCK_SKEW_SECONDS
        or now >= expires_at
    ):
        raise ValueError("final mutation checkpoint is expired or outside bounded clock skew")
    if not isinstance(expected_snapshot, Mapping) or expected_snapshot != current_snapshot:
        raise ValueError("final mutation authority snapshot drifted")
    authority_snapshot_digest(current_snapshot)
    if not all((reviewer_is_admin, key_current, signature_verified, attestation_verified)):
        raise ValueError("final mutation requires current admin, key, signature, and attestation proofs")


def reviewer_ready(*, kind: str, concrete_user_id: int | None, membership_verified: bool) -> bool:
    return kind == "user" and concrete_user_id is not None and membership_verified


def guard_descriptor_ready(descriptor: object | None) -> bool:
    if not isinstance(descriptor, Mapping):
        return False
    required = {
        "path",
        "blob_sha",
        "schema",
        "allowed_events",
        "allowed_refs",
        "receipt_schema_digest",
        "trust_policy_digest",
    }
    if set(descriptor) != required:
        return False
    return bool(
        isinstance(descriptor["path"], str)
        and descriptor["path"].startswith(".github/workflows/")
        and _hex(descriptor["blob_sha"], 40)
        and descriptor["schema"] == "aviato-managed-release-checkpoint/v1"
        and isinstance(descriptor["allowed_events"], (tuple, list))
        and tuple(descriptor["allowed_events"]) == ("workflow_dispatch",)
        and isinstance(descriptor["allowed_refs"], (tuple, list))
        and tuple(descriptor["allowed_refs"]) == ("default-branch",)
        and _hex(descriptor["receipt_schema_digest"], 64)
        and _hex(descriptor["trust_policy_digest"], 64)
    )
