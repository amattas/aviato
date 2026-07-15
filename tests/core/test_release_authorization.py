from __future__ import annotations

import importlib
import json
from pathlib import Path
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
        fingerprints={"rulesets": "e" * 64, "environment": "f" * 64},
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
    assert verify["permissions"] == {"contents": "read"}
    assert all("actions/checkout" not in str(step.get("uses", "")) for step in verify["steps"])


def test_managed_checkpoint_intake_attestation_job_sees_only_verified_fixed_artifact() -> None:
    document = yaml.safe_load((ROOT / "templates/consumer-protection-checkpoint.yml").read_text())
    attest = document["jobs"]["attest"]
    assert attest["needs"] == "verify"
    assert attest["permissions"] == {"contents": "read", "id-token": "write", "attestations": "write"}
    download = next(step for step in attest["steps"] if "download-artifact" in step.get("uses", ""))
    assert download["with"]["name"] == "verified-checkpoint"


def test_managed_checkpoint_template_is_generator_owned_and_byte_stable() -> None:
    assert (ROOT / "aviato/library/scaffold/files/wf-protection-checkpoint.yml").read_bytes() == (
        ROOT / "templates/consumer-protection-checkpoint.yml"
    ).read_bytes()


def test_checkpoint_workflow_is_generated_for_all_six_profiles_and_self_bootstrap() -> None:
    assert (ROOT / ".github/workflows/aviato-protection-checkpoint.yml").is_file()
    for name in ("node-service", "python-component", "python-library", "python-service", "swift-app"):
        assert "protection-checkpoint" in (ROOT / f"templates/profile-{name}.yml").read_text()


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
        fingerprints={"rulesets": "e" * 64, "environment": "f" * 64},
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
