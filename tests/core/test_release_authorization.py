from __future__ import annotations

import dataclasses
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _api() -> Any:
    return importlib.import_module("aviato.core.release_authorization")


def _checkpoint(**changes: Any) -> Any:
    values = dict(
        repository_id=7,
        repository="o/r",
        tag="1.2.3",
        sha="a" * 40,
        intended_actor="release-actor",
        collector="operator",
        reviewer="alice",
        submitter="bob",
        pin="1.0.0",
        snapshot_sha="b" * 40,
        protection_plan_id="c" * 64,
        protection_receipt_digest="d" * 64,
        authority_snapshot={"schema": "aviato-protection-authority-snapshot/v1", "repository": {"id": 7}},
        workflow_path=".github/workflows/aviato-protection-checkpoint.yml",
        workflow_blob_sha="1" * 40,
        workflow_ref="refs/heads/main",
        workflow_run_id=91,
        issued_at=1_700_000_000,
        expires_at=1_700_000_600,
    )
    values.update(changes)
    return _api().ManagedReleaseCheckpoint(**values)


def test_managed_checkpoint_collect_and_distinct_reviewer_sign_share_no_credentials() -> None:
    api = _api()
    unsigned = api.collect_checkpoint(_checkpoint(), credential_present=True)
    assert "token" not in unsigned.decode().lower()
    with pytest.raises(ValueError, match="distinct"):
        api.review_sign(unsigned, reviewer="operator", collector="operator", signer=lambda body: b"sig")


def test_collect_review_sign_verify_and_persist_use_one_exact_envelope() -> None:
    api = _api()
    unsigned = api.collect_checkpoint(_checkpoint(), credential_present=True)
    envelope = api.review_sign_envelope(
        unsigned,
        reviewer="alice",
        collector="operator",
        key_id="key-1",
        signer=lambda message: b"sig" if message == unsigned else b"wrong",
    )
    verified = api.verify_checkpoint_envelope(
        envelope,
        context=_verification_context(),
        resolve_key=lambda _key_id: _key(),
        verify_signature=lambda _key_bytes, message, signature: message == unsigned and signature == b"sig",
        now=1_700_000_100,
    )
    persisted: list[bytes] = []
    digest = api.persist_checkpoint_envelope(envelope, checkpoint=verified, persist=persisted.append)
    assert persisted == [envelope]
    assert digest == __import__("hashlib").sha256(envelope).hexdigest()


def test_managed_checkpoint_binds_repo_tag_sha_actor_reviewer_submitter_and_protection() -> None:
    body = _checkpoint().canonical_json
    for value in ("o/r", "1.2.3", "release-actor", "alice", "bob", "c" * 64):
        assert value in body


def test_managed_checkpoint_intake_is_default_branch_no_secret_and_injection_safe() -> None:
    document = yaml.safe_load((ROOT / "templates/consumer-protection-checkpoint.yml").read_text())
    trigger = document.get("on", document.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    assert document["permissions"] == {}
    verify = document["jobs"]["verify"]
    assert verify["permissions"] == {"actions": "read", "contents": "read", "issues": "read"}
    assert all("actions/checkout" not in str(step.get("uses", "")) for step in verify["steps"])


def test_managed_checkpoint_intake_attestation_job_sees_only_verified_fixed_artifact() -> None:
    document = yaml.safe_load((ROOT / "templates/consumer-protection-checkpoint.yml").read_text())
    attest = document["jobs"]["attest"]
    assert attest["needs"] == "verify"
    assert attest["permissions"] == {"contents": "read", "id-token": "write", "attestations": "write"}
    encoded = yaml.safe_dump(attest)
    assert "AVIATO_VERIFIER_APP" not in encoded
    assert "create-github-app-token" not in encoded
    assert "authority_verifier" not in encoded
    assert "gh api" not in encoded
    assert [step["name"] for step in attest["steps"]] == [
        "Download only verified artifact",
        "Attest fixed verified artifact",
    ]
    download = next(step for step in attest["steps"] if "download-artifact" in step.get("uses", ""))
    assert download["with"]["name"] == "verified-checkpoint"


def test_managed_checkpoint_template_is_generator_owned_and_byte_stable() -> None:
    assert (ROOT / "aviato/library/scaffold/files/wf-protection-checkpoint.yml").read_bytes() == (
        ROOT / "templates/consumer-protection-checkpoint.yml"
    ).read_bytes()


def test_checkpoint_workflow_is_generated_for_all_six_profiles_and_self_bootstrap() -> None:
    from aviato.core.onboarding import resolved_artifacts
    from aviato.core.registry import Registry
    from aviato.validation import _TEMPLATE_EXAMPLE_VARS

    assert (ROOT / ".github/workflows/aviato-protection-checkpoint.yml").is_file()
    for name in ("node-service", "python-component", "python-library", "python-service", "swift-app"):
        artifacts = resolved_artifacts(
            Registry(ROOT / "aviato/library"),
            name,
            _TEMPLATE_EXAMPLE_VARS[name],
            pin="1",
        )
        checkpoint = next(
            artifact
            for artifact in artifacts
            if artifact.output == ".github/workflows/aviato-protection-checkpoint.yml"
        )
        assert checkpoint.body == (ROOT / "templates/consumer-protection-checkpoint.yml").read_text()


def test_self_bootstrap_caller_has_generator_owned_closed_promotion_mode() -> None:
    body = (ROOT / ".github/workflows/aviato-ci.yml").read_text()
    assert "promotion" in body and "checkpoint-digest" in body


def test_privileged_jobs_compile_exact_managed_authorization_guard_descriptor() -> None:
    from aviato.core.compiler import compile_desired_state
    from aviato.core.composition import resolve_profile
    from aviato.core.registry import Registry
    from aviato.paths import MODULE_SOURCE_ROOT
    from aviato.validation import _TEMPLATE_EXAMPLE_VARS

    desired = compile_desired_state(
        Registry(MODULE_SOURCE_ROOT),
        resolve_profile(Registry(MODULE_SOURCE_ROOT), "python-library"),
        _TEMPLATE_EXAMPLE_VARS["python-library"],
        pin="1",
    )
    guard = desired.authorization_guard
    assert guard is not None
    artifact = next(item for item in desired.artifacts if item.output_path == guard.path)
    blob = artifact.body.encode("utf-8")
    expected = (
        __import__("hashlib").sha1(f"blob {len(blob)}\0".encode("ascii") + blob, usedforsecurity=False).hexdigest()
    )
    assert guard.blob_sha == expected and guard.allowed_refs == ("default-branch",)


def test_privileged_job_without_guard_is_graph_invalid_and_non_ready() -> None:
    assert _api().guard_descriptor_ready(None) is False


def test_managed_release_gate_verifies_one_exact_fresh_checkpoint_and_actual_actor() -> None:
    assert _api().promotion_ready(
        _checkpoint(), actor="release-actor", tag="1.2.3", sha="a" * 40, digest=_checkpoint().digest, now=1_700_000_100
    )


def test_every_managed_privileged_job_rechecks_checkpoint_before_privilege() -> None:
    manifest = yaml.safe_load((ROOT / "aviato/library/pipelines.yaml").read_text())
    guarded = []
    for pipeline in manifest.values():
        if not isinstance(pipeline, dict):
            continue
        for job in (pipeline.get("jobs") or {}).values():
            if not isinstance(job, dict) or not job.get("authorization_gate"):
                continue
            guarded.append(job)
            gate = job["authorization_gate"]
            assert gate in job["needs"]
            fragment = yaml.safe_load((ROOT / "aviato/library" / job["fragment"]).read_text())
            rendered = yaml.safe_dump(fragment)
            assert f"needs.{gate}.outputs.gated-sha" in rendered
            assert f"needs.{gate}.outputs.checkpoint-digest" in rendered
    assert len(guarded) == 8


def test_release_proposal_merge_stops_before_tag_floating_tag_and_github_release() -> None:
    body = (ROOT / ".github/workflows/reusable-release.yml").read_text()
    assert "promotion" in body and "phase=tag" not in body


def test_promotion_dispatch_binds_exact_merged_sha_tag_actor_and_checkpoint_digest() -> None:
    body = (ROOT / ".github/workflows/reusable-release.yml").read_text()
    for value in ("merged-sha", "intended-tag", "intended-actor", "checkpoint-digest"):
        assert value in body


def test_missing_stale_or_mismatched_checkpoint_blocks_all_release_mutations() -> None:
    assert not _api().promotion_ready(
        _checkpoint(), actor="wrong", tag="1.2.3", sha="a" * 40, digest=_checkpoint().digest, now=1_700_000_100
    )


def test_promotion_dispatch_uses_trusted_default_branch_code_and_no_consumer_checkout() -> None:
    body = (ROOT / ".github/workflows/reusable-release.yml").read_text()
    assert "promotion" in body and "consumer checkout" not in body.lower()


def test_team_only_reviewer_forged_membership_and_missing_checkpoint_are_non_ready() -> None:
    assert not _api().reviewer_ready(kind="team", concrete_user_id=None, membership_verified=False)


def _envelope_bytes(document: dict[str, Any] | None = None, **document_changes: Any) -> bytes:
    checkpoint = _checkpoint()
    checkpoint_document = json.loads(checkpoint.canonical_json) if document is None else document
    checkpoint_document.update(document_changes)
    envelope = {
        "schema": "aviato-managed-release-checkpoint-envelope/v1",
        "key_id": "key-1",
        "algorithm": "ssh-ed25519",
        "checkpoint": checkpoint_document,
        "signature": "c2ln",
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")


def _verification_context() -> Any:
    api = _api()
    return api.CheckpointVerificationContext(
        repository_id=7,
        repository="o/r",
        intended_actor="release-actor",
        submitter="bob",
        reviewer="alice",
        reviewer_kind="user",
        reviewer_database_id=11,
        reviewer_is_admin=True,
        workflow_path=".github/workflows/aviato-protection-checkpoint.yml",
        workflow_blob_sha="1" * 40,
        workflow_ref="refs/heads/main",
        workflow_run_id=91,
        source_sha="a" * 40,
        protection_plan_id="c" * 64,
        protection_receipt_digest="d" * 64,
        authority_snapshot={"schema": "aviato-protection-authority-snapshot/v1", "repository": {"id": 7}},
    )


def _key(**changes: Any) -> Any:
    values = {"key_id": "key-1", "reviewer": "alice", "public_key": b"pk", "current": True}
    values.update(changes)
    return _api().RegisteredReviewerKey(**values)


def test_checkpoint_envelope_accepts_only_exact_canonical_signed_document() -> None:
    api = _api()
    seen: list[bytes] = []

    def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
        assert public_key == b"pk" and signature == b"sig"
        seen.append(message)
        return True

    verified = api.verify_checkpoint_envelope(
        _envelope_bytes(),
        context=_verification_context(),
        resolve_key=lambda key_id: _key() if key_id == "key-1" else None,
        verify_signature=verify,
        now=1_700_000_100,
    )
    assert verified.digest == _checkpoint().digest
    assert seen == [verified.canonical_bytes]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: {**json.loads(body), "unexpected": "smuggled"},
        lambda body: {key: value for key, value in json.loads(body).items() if key != "sha"},
        lambda body: {**json.loads(body), "repository_id": True},
        lambda body: {**json.loads(body), "expires_at": "2023-11-14T22:23:20Z"},
    ],
)
def test_checkpoint_envelope_rejects_extra_missing_and_type_confused_fields(mutation: Any) -> None:
    api = _api()
    mutated = mutation(_checkpoint().canonical_json)
    raw = _envelope_bytes(document=mutated)
    with pytest.raises(ValueError):
        api.verify_checkpoint_envelope(
            raw,
            context=_verification_context(),
            resolve_key=lambda _key_id: _key(),
            verify_signature=lambda *_args: True,
            now=1_700_000_100,
        )


@pytest.mark.parametrize(
    ("key_change", "context_change", "now"),
    [
        ({"current": False}, {}, 1_700_000_100),
        ({"revoked": True}, {}, 1_700_000_100),
        ({}, {"reviewer_is_admin": False}, 1_700_000_100),
        ({}, {"workflow_blob_sha": "9" * 40}, 1_700_000_100),
        ({}, {"protection_receipt_digest": "9" * 64}, 1_700_000_100),
        ({}, {}, 1_700_000_600),
    ],
)
def test_checkpoint_envelope_rejects_revoked_expired_or_stale_live_evidence(
    key_change: dict[str, Any], context_change: dict[str, Any], now: int
) -> None:
    api = _api()
    context = _verification_context()
    if context_change:
        context = api.CheckpointVerificationContext(**{**vars(context), **context_change})
    with pytest.raises(ValueError):
        api.verify_checkpoint_envelope(
            _envelope_bytes(),
            context=context,
            resolve_key=lambda _key_id: _key(**key_change),
            verify_signature=lambda *_args: True,
            now=now,
        )


def test_managed_checkpoint_intake_verified_artifact_has_bounded_base64url_input() -> None:
    body = (ROOT / "templates/consumer-protection-checkpoint.yml").read_text()
    assert "base64url" in body.lower() and "MAX_" in body


def test_checkpoint_rejects_ten_year_ttl_and_excessive_future_skew() -> None:
    api = _api()
    with pytest.raises(ValueError, match="TTL"):
        _checkpoint(expires_at=1_700_000_000 + 315_360_000)

    checkpoint = _checkpoint(issued_at=1_700_000_120, expires_at=1_700_000_240)
    with pytest.raises(ValueError, match="clock skew"):
        api.verify_checkpoint_envelope(
            _envelope_bytes(document=json.loads(checkpoint.canonical_json)),
            context=_verification_context(),
            resolve_key=lambda _key_id: _key(),
            verify_signature=lambda *_args: True,
            now=1_700_000_000,
        )


def test_checkpoint_intake_preserves_and_attests_exact_signed_envelope_with_minimum_reads() -> None:
    workflow = yaml.safe_load((ROOT / "templates/consumer-protection-checkpoint.yml").read_text())
    verify = workflow["jobs"]["verify"]
    assert verify["permissions"] == {"actions": "read", "contents": "read", "issues": "read"}
    upload = next(step for step in verify["steps"] if str(step.get("name", "")).startswith("Upload"))
    assert upload["with"]["path"].endswith("verified-checkpoint-envelope.json")
    attest = workflow["jobs"]["attest"]
    subject = next(step for step in attest["steps"] if str(step.get("name", "")).startswith("Attest"))
    assert subject["with"]["subject-path"].endswith("verified-checkpoint-envelope.json")


def test_checkpoint_intake_authorizes_only_an_immutable_current_admin_signed_receipt_comment() -> None:
    body = (ROOT / "templates/consumer-protection-checkpoint.yml").read_text()
    assert "issues/{issue['number']}/comments?per_page=100" in body
    assert "aviato-protection-receipt-envelope/v1" in body
    assert 'receipt_comment.get("created_at") != receipt_comment.get("updated_at")' in body
    assert 'receipt_author.get("login") != receipt_envelope["principal"]' in body
    assert "receipt signer is not a current concrete repository admin" in body
    assert "receipt SSH signature verification failed" in body
    assert 'issue.get("body")' not in body
    assert "lastEditedAt" in body and "isMinimized" in body and "databaseId" in body
    assert "authority_snapshot" in body
    assert 'receipt.get("surface_fingerprints")' not in body


def test_release_gate_selects_exactly_one_trusted_attested_unexpired_intake_run() -> None:
    api = _api()
    trusted = api.CheckpointIntakeRun(
        run_id=91,
        workflow_path=".github/workflows/aviato-protection-checkpoint.yml",
        workflow_blob_sha="1" * 40,
        workflow_ref="refs/heads/main",
        head_sha="a" * 40,
        tag="1.2.3",
        envelope_digest="2" * 64,
        expires_at=1_700_000_300,
        conclusion="success",
        attestation_verified=True,
    )
    assert (
        api.select_checkpoint_intake_run(
            [trusted],
            workflow_path=trusted.workflow_path,
            workflow_blob_sha=trusted.workflow_blob_sha,
            workflow_ref=trusted.workflow_ref,
            head_sha=trusted.head_sha,
            tag=trusted.tag,
            envelope_digest=trusted.envelope_digest,
            now=1_700_000_100,
        )
        == trusted
    )
    with pytest.raises(ValueError, match="exactly one"):
        api.select_checkpoint_intake_run(
            [trusted, trusted],
            workflow_path=trusted.workflow_path,
            workflow_blob_sha=trusted.workflow_blob_sha,
            workflow_ref=trusted.workflow_ref,
            head_sha=trusted.head_sha,
            tag=trusted.tag,
            envelope_digest=trusted.envelope_digest,
            now=1_700_000_100,
        )
    with pytest.raises(ValueError, match="exactly one"):
        api.select_checkpoint_intake_run(
            [dataclasses.replace(trusted, attestation_verified=False)],
            workflow_path=trusted.workflow_path,
            workflow_blob_sha=trusted.workflow_blob_sha,
            workflow_ref=trusted.workflow_ref,
            head_sha=trusted.head_sha,
            tag=trusted.tag,
            envelope_digest=trusted.envelope_digest,
            now=1_700_000_100,
        )


def test_guard_descriptor_requires_full_typed_trust_contract() -> None:
    descriptor = {
        "path": ".github/workflows/aviato-protection-checkpoint.yml",
        "blob_sha": "1" * 40,
        "schema": "aviato-managed-release-checkpoint/v1",
    }
    assert not _api().guard_descriptor_ready(descriptor)


def test_checkpoint_accepts_two_person_submitter_actor_and_rejects_reviewer_overlap() -> None:
    checkpoint = _checkpoint(submitter="release-actor", intended_actor="release-actor")
    assert checkpoint.submitter == checkpoint.intended_actor
    with pytest.raises(ValueError, match="reviewer"):
        _checkpoint(reviewer="release-actor", submitter="release-actor", intended_actor="release-actor")


def test_checkpoint_schema_carries_canonical_authority_snapshot_not_arbitrary_fingerprints() -> None:
    fields = set(_api().ManagedReleaseCheckpoint.__dataclass_fields__)
    assert "authority_snapshot" in fields
    assert "fingerprints" not in fields


@pytest.mark.parametrize(
    "change",
    (
        {"now": 1_700_000_301},
        {"current_snapshot": {"schema": "aviato-protection-authority-snapshot/v1", "drift": True}},
        {"reviewer_is_admin": False},
        {"key_current": False},
        {"signature_verified": False},
        {"attestation_verified": False},
    ),
)
def test_final_mutation_authority_rejects_expiry_snapshot_drift_revocation_and_invalid_proofs(
    change: dict[str, Any],
) -> None:
    api = _api()
    snapshot = {"schema": "aviato-protection-authority-snapshot/v1", "repository": {"id": 7}}
    values: dict[str, Any] = {
        "checkpoint": SimpleNamespace(
            issued_at=1_700_000_000,
            expires_at=1_700_000_300,
            authority_snapshot=snapshot,
        ),
        "current_snapshot": snapshot,
        "now": 1_700_000_100,
        "reviewer_is_admin": True,
        "key_current": True,
        "signature_verified": True,
        "attestation_verified": True,
    }
    values.update(change)
    with pytest.raises(ValueError):
        api.require_final_mutation_authority(**values)


def test_final_mutation_authority_accepts_exact_fresh_current_proofs() -> None:
    api = _api()
    snapshot = {"schema": "aviato-protection-authority-snapshot/v1", "repository": {"id": 7}}
    checkpoint = SimpleNamespace(
        issued_at=1_700_000_000,
        expires_at=1_700_000_300,
        authority_snapshot=snapshot,
    )
    api.require_final_mutation_authority(
        checkpoint=checkpoint,
        current_snapshot=snapshot,
        now=1_700_000_100,
        reviewer_is_admin=True,
        key_current=True,
        signature_verified=True,
        attestation_verified=True,
    )
