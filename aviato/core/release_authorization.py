from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

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
    issued_at: int
    expires_at: int
    schema: str = "aviato-managed-release-checkpoint/v1"

    def __post_init__(self) -> None:
        if self.repository_id <= 0 or "/" not in self.repository or self.collector == self.reviewer:
            raise ValueError("checkpoint requires repository identity and a distinct reviewer")
        if self.reviewer in {self.intended_actor, self.submitter}:
            raise ValueError("checkpoint reviewer must differ from actor and workflow submitter")
        if len(self.sha) != 40 or len(self.snapshot_sha) != 40 or len(self.workflow_blob_sha) != 40:
            raise ValueError("checkpoint SHAs must be 40-hex")
        if self.expires_at <= self.issued_at:
            raise ValueError("checkpoint expiry must be after issue time")
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


def verify_signed_checkpoint(
    checkpoint: ManagedReleaseCheckpoint,
    *,
    signature_valid: bool,
    edited: bool,
    author_is_admin: bool,
    key_current: bool,
    now: int,
) -> bool:
    return (
        signature_valid
        and not edited
        and author_is_admin
        and key_current
        and checkpoint.issued_at <= now < checkpoint.expires_at
    )


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
