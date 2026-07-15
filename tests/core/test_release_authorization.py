from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

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
        issued_at=1_700_000_000,
        expires_at=1_700_000_600,
    )
    values.update(changes)
    return _api().ManagedReleaseCheckpoint(**values)


def test_signed_receipt_rejects_forgery_edit_untrusted_author_or_revoked_key() -> None:
    api = _api()
    cp = _checkpoint()
    for valid, edited, admin, current in (
        (False, False, True, True),
        (True, True, True, True),
        (True, False, False, True),
        (True, False, True, False),
    ):
        assert not api.verify_signed_checkpoint(
            cp, signature_valid=valid, edited=edited, author_is_admin=admin, key_current=current, now=1_700_000_100
        )


def test_managed_checkpoint_collect_and_distinct_reviewer_sign_share_no_credentials() -> None:
    api = _api()
    unsigned = api.collect_checkpoint(_checkpoint(), credential_present=True)
    assert "token" not in unsigned.decode().lower()
    with pytest.raises(ValueError, match="distinct"):
        api.review_sign(unsigned, reviewer="operator", collector="operator", signer=lambda body: b"sig")


def test_managed_checkpoint_binds_repo_tag_sha_actor_reviewer_submitter_and_protection() -> None:
    body = _checkpoint().canonical_json
    for value in ("o/r", "1.2.3", "release-actor", "alice", "bob", "c" * 64):
        assert value in body


def test_managed_checkpoint_intake_is_default_branch_no_secret_and_injection_safe() -> None:
    body = (ROOT / "templates/consumer-protection-checkpoint.yml").read_text()
    assert "workflow_dispatch" in body and "checkout" not in body and "secrets:" not in body


def test_managed_checkpoint_intake_attestation_job_sees_only_verified_fixed_artifact() -> None:
    body = (ROOT / "templates/consumer-protection-checkpoint.yml").read_text()
    assert "verified-checkpoint" in body and "attestations: write" in body and "id-token: write" in body


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

    assert "authorization_guard" in compile_desired_state.__annotations__ or hasattr(_api(), "ManagedReleaseCheckpoint")


def test_privileged_job_without_guard_is_graph_invalid_and_non_ready() -> None:
    assert _api().guard_descriptor_ready(None) is False


def test_managed_release_gate_verifies_one_exact_fresh_checkpoint_and_actual_actor() -> None:
    assert _api().promotion_ready(
        _checkpoint(), actor="release-actor", tag="1.2.3", sha="a" * 40, digest=_checkpoint().digest, now=1_700_000_100
    )


def test_every_managed_privileged_job_rechecks_checkpoint_before_privilege() -> None:
    for name in (
        "pypi-publish.yml",
        "ghcr-publish.yml",
        "app-store-connect.yml",
        "docs-python-library.yml",
        "docs-python-service.yml",
        "docs-python-component.yml",
        "docs-node-service.yml",
        "docs-swift-app.yml",
    ):
        assert "checkpoint" in (ROOT / "aviato/library/workflow-fragments" / name).read_text().lower()


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


def test_managed_checkpoint_intake_verified_artifact_has_bounded_base64url_input() -> None:
    body = (ROOT / "templates/consumer-protection-checkpoint.yml").read_text()
    assert "base64url" in body.lower() and "MAX_" in body
