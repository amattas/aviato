from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import json
import ssl
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from aviato import cli
from aviato.plugins import release_mutations


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _protected_files() -> list[dict[str, str]]:
    return sorted(
        [
            {"path": "/.github/CODEOWNERS", "mode": "100644", "sha256": "1" * 64},
            {"path": "/.github/aviato-privileged-review.json", "mode": "100644", "sha256": "2" * 64},
            {"path": "/.github/workflows/aviato-privileged-review.yml", "mode": "100644", "sha256": "3" * 64},
            {"path": "/aviato/cli.py", "mode": "100644", "sha256": "4" * 64},
            {"path": "/aviato/library/policy.yml", "mode": "100644", "sha256": "5" * 64},
            {"path": "/aviato/library/privileged-execution-manifest.json", "mode": "100644", "sha256": "6" * 64},
            {"path": "/aviato/library/privileged-review-policy.json", "mode": "100644", "sha256": "7" * 64},
            {"path": "/aviato/library/rulesets/protect-default-branch.json", "mode": "100644", "sha256": "8" * 64},
            {"path": "/aviato/plugins/privileged_review.py", "mode": "100644", "sha256": "9" * 64},
            {"path": "/aviato/plugins/release_mutations.py", "mode": "100644", "sha256": "a" * 64},
            {"path": "/MANIFEST.in", "mode": "100644", "sha256": "c" * 64},
            {"path": "/pyproject.toml", "mode": "100644", "sha256": "d" * 64},
            {"path": "/scripts/regen-privileged-execution-manifest.py", "mode": "100755", "sha256": "b" * 64},
        ],
        key=lambda item: item["path"],
    )


def _ruleset_payload() -> dict[str, Any]:
    return {
        "id": 17482301,
        "node_id": "RRS_live",
        "source": "amattas/aviato",
        "source_type": "Repository",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "current_user_can_bypass": False,
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 2,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": True,
                    "require_last_push_approval": True,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": "common-lint / Common lint"},
                        {"context": "security / Security baseline heartbeat"},
                    ],
                },
            },
        ],
    }


def _review(reviewer_id: int, login: str, review_id: int) -> dict[str, Any]:
    return {
        "review_id": review_id,
        "node_id": f"PRR_{review_id}",
        "reviewer_database_id": reviewer_id,
        "reviewer_login": login,
        "state": "APPROVED",
        "commit_sha": "c" * 40,
        "submitted_at": "2026-07-15T13:01:00Z",
        "dismissed": False,
        "edited": False,
        "is_author": False,
        "eligible_codeowner_paths": [item["path"] for item in _protected_files()],
        "team_database_id": None,
        "team_membership": None,
    }


def _environment() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "privileged-review",
        "can_admins_bypass": False,
        "prevent_self_review": True,
        "reviewers": [
            {"type": "User", "database_id": 2, "node_id": "U_2", "login": "reviewer-one"},
            {"type": "User", "database_id": 3, "node_id": "U_3", "login": "reviewer-two"},
        ],
        "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False},
    }
    payload["payload_sha256"] = _digest(payload)
    return payload


def _evidence() -> dict[str, Any]:
    ruleset = _ruleset_payload()
    protected = _protected_files()
    return {
        "schema": "aviato-privileged-review-evidence/v1",
        "status": "approved",
        "lifecycle": "consumed",
        "repository": {
            "database_id": 123,
            "node_id": "R_aviato",
            "full_name": "amattas/aviato",
            "default_branch": "main",
        },
        "pull_request": {
            "number": 99,
            "author_database_id": 1,
            "author_login": "author",
            "base_sha": "a" * 40,
            "head_sha": "c" * 40,
            "last_push_sha": "c" * 40,
            "last_push_at": "2026-07-15T13:00:00Z",
            "merged_sha": "d" * 40,
            "protected_tree_root": _digest(protected),
        },
        "protected_files": protected,
        "changed_protected_paths": [item["path"] for item in protected],
        "reviews": [_review(2, "reviewer-one", 201), _review(3, "reviewer-two", 202)],
        "ruleset": {"payload": ruleset, "payload_sha256": _digest(ruleset)},
        "collector": {
            "app_id": 1001,
            "installation_id": 2001,
            "app_slug": "aviato-verifier",
            "permissions": {
                "actions": "read",
                "administration": "read",
                "contents": "read",
                "members": "read",
                "metadata": "read",
                "pull_requests": "read",
            },
            "repository_ids": [123],
            "suspended_at": None,
        },
        "environment": _environment(),
        "issuer": "aviato-privileged-review",
        "workflow": {
            "repository_id": 123,
            "path": ".github/workflows/aviato-privileged-review.yml",
            "ref": "refs/heads/main",
            "blob_sha": "e" * 40,
            "blob_sha256": "e" * 64,
            "run_head_sha": "d" * 40,
            "run_id": 500,
            "workflow_database_id": 501,
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "actor_database_id": 9,
            "actor_login": "trusted-operator",
            "triggering_actor_database_id": 9,
            "triggering_actor_login": "trusted-operator",
            "environment": "privileged-review",
        },
        "trust_root": {
            "base_sha": "a" * 40,
            "policy_blob_sha": "0" * 40,
            "policy_sha256": _digest(_policy()) if "_policy" in globals() else "0" * 64,
        },
        "issued_at": 1_784_119_260,
        "expires_at": 1_784_120_160,
        "key_id": "review-key-1",
        "key_version": 1,
        "nonce": "f" * 64,
    }


def _envelope(evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": "aviato-privileged-review-envelope/v1",
        "algorithm": "ssh-ed25519",
        "evidence": evidence or _evidence(),
        "signature": base64.urlsafe_b64encode(b"signature").decode().rstrip("="),
    }


def _policy() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "minimum_approvals": 2,
        "require_non_author": True,
        "require_code_owner_review": True,
        "require_last_push_approval": True,
        "dismiss_stale_reviews_on_push": True,
        "maximum_attestation_ttl_seconds": 34_560_000,
        "required_status_checks": ["common-lint / Common lint", "security / Security baseline heartbeat"],
        "trusted_issuer": "aviato-privileged-review",
        "trusted_environment": "privileged-review",
        "trusted_workflow_path": ".github/workflows/aviato-privileged-review.yml",
        "trusted_signing_keys": [
            {
                "key_id": "review-key-1",
                "key_version": 1,
                "issuer": "aviato-privileged-review",
                "public_key": "ssh-ed25519 AAAA-test",
            }
        ],
        "revoked_key_versions": [],
        "reviewer_database_ids": [2, 3],
        "team_database_ids": [],
        "protected_paths": [item["path"] for item in _protected_files()],
    }


def _verify(
    envelope: dict[str, Any] | None = None,
    *,
    live: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    current_policy: dict[str, Any] | None = None,
    signature_ok: bool = True,
) -> list[str]:
    return release_mutations.verify_privileged_review_envelope(
        envelope or _envelope(),
        trusted_base_policy=policy or _policy(),
        current_policy=current_policy or copy.deepcopy(policy or _policy()),
        live_evidence=live or copy.deepcopy((envelope or _envelope())["evidence"]),
        now=1_784_119_300,
        verify_signature=lambda *_args: signature_ok,
    )


def test_canonical_signed_live_evidence_is_required_for_approval() -> None:
    evidence = _evidence()
    evidence["trust_root"]["policy_sha256"] = _digest(_policy())
    envelope = _envelope(evidence)
    assert _verify(envelope) == []
    forged = copy.deepcopy(envelope)
    forged["signature"] = "Zm9yZ2Vk"
    assert any("signature" in error for error in _verify(forged, signature_ok=False))


def test_candidate_cannot_replace_policy_signer_and_signature_together() -> None:
    trusted = _policy()
    attacker_policy = copy.deepcopy(trusted)
    attacker_policy["trusted_signing_keys"] = [
        {
            "key_id": "attacker-key",
            "key_version": 1,
            "issuer": "aviato-privileged-review",
            "public_key": "ssh-ed25519 AAAA-attacker",
        }
    ]
    evidence = _evidence()
    evidence["key_id"] = "attacker-key"
    evidence["trust_root"]["policy_sha256"] = _digest(attacker_policy)
    envelope = _envelope(evidence)
    errors = release_mutations.verify_privileged_review_envelope(
        envelope,
        trusted_base_policy=trusted,
        current_policy=trusted,
        live_evidence=copy.deepcopy(evidence),
        now=1_784_119_300,
        verify_signature=lambda *_args: True,
    )
    assert any("trusted base" in error or "key" in error for error in errors)


@pytest.mark.parametrize(
    ("mutation", "needle"),
    (
        (lambda e: e.pop("signature"), "signature"),
        (lambda e: e["evidence"].update(expires_at=1_784_119_299), "fresh"),
        (lambda e: e["evidence"].update(key_version=9), "key"),
        (lambda e: e["evidence"].update(key_version=2), "revoked"),
        (lambda e: e["evidence"]["pull_request"].update(head_sha="0" * 40), "live"),
        (lambda e: e["evidence"]["pull_request"].update(last_push_sha="0" * 40), "live"),
    ),
)
def test_unsigned_stale_revoked_and_replayed_evidence_is_rejected(mutation: Any, needle: str) -> None:
    envelope = _envelope()
    live = copy.deepcopy(envelope["evidence"])
    policy = _policy()
    if needle == "revoked":
        policy["trusted_signing_keys"][0]["key_version"] = 2
        policy["revoked_key_versions"] = [2]
    mutation(envelope)
    assert any(needle in error for error in _verify(envelope, live=live, policy=policy))


@pytest.mark.parametrize(
    "mutation",
    (
        lambda e: e["reviews"][1].update(reviewer_database_id=2),
        lambda e: e["reviews"][0].update(reviewer_database_id=1, is_author=True),
        lambda e: e["reviews"][0].update(reviewer_database_id=999),
        lambda e: e["reviews"][0].update(review_id=999999),
        lambda e: e["reviews"][0].update(state="DISMISSED", dismissed=True),
        lambda e: e["reviews"][0].update(edited=True),
        lambda e: e["reviews"][0].update(commit_sha="0" * 40),
        lambda e: e["reviews"][0].update(submitted_at="2026-07-15T12:00:00Z"),
        lambda e: e["reviews"][0].update(eligible_codeowner_paths=[]),
        lambda e: e["reviews"][0].update(team_database_id=88, team_membership=False),
    ),
)
def test_review_identity_author_freshness_and_codeowner_attacks_are_rejected(mutation: Any) -> None:
    envelope = _envelope()
    live = copy.deepcopy(envelope["evidence"])
    mutation(envelope["evidence"])
    assert _verify(envelope, live=live)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda r: r.update(enforcement="disabled"),
        lambda r: r.update(bypass_actors=[{"actor_id": 1, "actor_type": "OrganizationAdmin"}]),
        lambda r: r.update(current_user_can_bypass=True),
        lambda r: r.update(source="attacker/repo"),
        lambda r: r["conditions"]["ref_name"].update(include=["refs/heads/other"]),
        lambda r: next(x for x in r["rules"] if x["type"] == "pull_request")["parameters"].update(
            required_approving_review_count=1
        ),
        lambda r: next(x for x in r["rules"] if x["type"] == "pull_request")["parameters"].update(
            dismiss_stale_reviews_on_push=False
        ),
        lambda r: next(x for x in r["rules"] if x["type"] == "pull_request")["parameters"].update(
            require_code_owner_review=False
        ),
        lambda r: next(x for x in r["rules"] if x["type"] == "pull_request")["parameters"].update(
            require_last_push_approval=False
        ),
        lambda r: next(x for x in r["rules"] if x["type"] == "required_status_checks")["parameters"].update(
            required_status_checks=[]
        ),
    ),
)
def test_disabled_weak_bypassed_or_wrong_target_ruleset_is_rejected(mutation: Any) -> None:
    envelope = _envelope()
    live = copy.deepcopy(envelope["evidence"])
    ruleset = envelope["evidence"]["ruleset"]["payload"]
    mutation(ruleset)
    envelope["evidence"]["ruleset"]["payload_sha256"] = _digest(ruleset)
    assert _verify(envelope, live=live)


def test_live_unavailability_ambiguity_and_changed_protected_hash_fail_closed() -> None:
    assert any(
        "live" in error
        for error in release_mutations.verify_privileged_review_envelope(
            _envelope(),
            trusted_base_policy=_policy(),
            current_policy=_policy(),
            live_evidence=None,
            now=1_784_119_300,
            verify_signature=lambda *_: True,
        )
    )
    envelope = _envelope()
    live = copy.deepcopy(envelope["evidence"])
    live["reviews"].append(copy.deepcopy(live["reviews"][0]))
    assert _verify(envelope, live=live)


def test_durable_attestation_older_than_fifteen_minutes_requires_fresh_live_match() -> None:
    envelope = _envelope()
    envelope["evidence"]["issued_at"] = 1_784_115_000
    envelope["evidence"]["expires_at"] = 1_786_000_000
    live = copy.deepcopy(envelope["evidence"])
    assert _verify(envelope, live=live) == []
    live["ruleset"]["payload"]["enforcement"] = "disabled"
    live["ruleset"]["payload_sha256"] = _digest(live["ruleset"]["payload"])
    assert any("live" in error for error in _verify(envelope, live=live))

    supported_release = _envelope()
    supported_release["evidence"]["issued_at"] = 1_768_567_300
    supported_release["evidence"]["expires_at"] = 1_803_127_300
    assert _verify(supported_release, live=copy.deepcopy(supported_release["evidence"])) == []

    exactly_expired = _envelope()
    exactly_expired["evidence"]["expires_at"] = 1_784_119_300
    assert any("fresh" in error for error in _verify(exactly_expired, live=copy.deepcopy(exactly_expired["evidence"])))

    overlong = _envelope()
    overlong["evidence"]["issued_at"] = 1_784_119_260
    overlong["evidence"]["expires_at"] = 1_784_119_260 + 34_560_001
    assert any("fresh" in error for error in _verify(overlong, live=copy.deepcopy(overlong["evidence"])))


@pytest.mark.parametrize("revocation", ("remove", "revoke", "rotate", "reviewer"))
def test_current_default_branch_policy_can_only_remove_or_revoke_historical_authority(revocation: str) -> None:
    current = _policy()
    if revocation == "remove":
        current["trusted_signing_keys"] = []
    elif revocation == "revoke":
        current["revoked_key_versions"] = [1]
    elif revocation == "rotate":
        current["trusted_signing_keys"][0]["public_key"] = "ssh-ed25519 AAAA-rotated"
    else:
        current["reviewer_database_ids"] = [2]
    assert _verify(current_policy=current)


def test_current_policy_strengthening_cannot_be_silently_ignored() -> None:
    current = _policy()
    current["minimum_approvals"] = 3
    assert any("3 distinct" in error for error in _verify(current_policy=current))
    current = _policy()
    current["required_status_checks"].append("new/current check")
    assert any("status checks" in error for error in _verify(current_policy=current))
    current = _policy()
    current["require_code_owner_review"] = False
    assert any("require_code_owner_review" in error for error in _verify(current_policy=current))


def test_unrelated_default_branch_advance_with_identical_current_policy_does_not_expire_snapshot() -> None:
    envelope = _envelope()
    # Current branch/blob identity is intentionally runtime-only and therefore
    # absent from the signed trust root. A race-stable byte-identical policy
    # remains a valid intersection after unrelated main commits.
    assert set(envelope["evidence"]["trust_root"]) == {"base_sha", "policy_blob_sha", "policy_sha256"}
    assert _verify(envelope, current_policy=copy.deepcopy(_policy())) == []
    envelope = _envelope()
    live = copy.deepcopy(envelope["evidence"])
    envelope["evidence"]["protected_files"][8]["sha256"] = "0" * 64
    assert _verify(envelope, live=live)


def test_forged_legacy_approved_record_never_authorizes_packaged_gate(tmp_path: Path) -> None:
    (tmp_path / "privileged-review-policy.json").write_text(json.dumps(_policy()))
    (tmp_path / "privileged-execution-manifest.json").write_text("[]")
    forged = {
        "schema_version": 1,
        "status": "approved",
        "author_database_id": 1,
        "reviewer_database_ids": [2, 3],
        "approvals": [
            {"reviewer_database_id": 2, "review_id": 11},
            {"reviewer_database_id": 3, "review_id": 12},
        ],
    }
    (tmp_path / "privileged-review-attestation.json").write_text(json.dumps(forged))
    errors = release_mutations.verify_packaged_privileged_review_readiness(tmp_path)
    assert any("signed" in error or "envelope" in error for error in errors)


def test_generator_refuses_arbitrary_unsigned_approved_review_record(tmp_path: Path) -> None:
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps({"schema_version": 2, "status": "approved", "approvals": []}))
    with pytest.raises(SystemExit, match="signed|pending|live"):
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("regen_privileged", Path("scripts/regen-privileged-execution-manifest.py"))
        assert spec is not None and spec.loader is not None
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_review_record(forged, "[]\n")


def test_network_client_is_exact_origin_non_redirecting_and_rejects_proxy_tls_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aviato.plugins import privileged_review

    for name in privileged_review._DANGEROUS_NETWORK_ENV:
        monkeypatch.delenv(name, raising=False)
    transcript: list[tuple[str, Any]] = []

    class Response:
        status = 200

        def read(self, _maximum: int) -> bytes:
            return b'{"ok":true}'

    class Connection:
        def __init__(self, host: str, **kwargs: object) -> None:
            transcript.append(("connect", (host, kwargs)))

        def request(self, method: str, path: str, **kwargs: object) -> None:
            transcript.append(("request", (method, path, kwargs)))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            transcript.append(("close", None))

    monkeypatch.setattr(ssl, "create_default_context", lambda: cast(ssl.SSLContext, object()))
    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    assert privileged_review._request_json("/repos/amattas/aviato", token="app-token") == {"ok": True}
    assert transcript[0][0] == "connect"
    host, options = transcript[0][1]
    assert host == "api.github.com"
    assert all("proxy" not in key.lower() for key in options)
    method, path, request_options = transcript[1][1]
    assert (method, path) == ("GET", "/repos/amattas/aviato")
    assert request_options["headers"]["Authorization"] == "Bearer app-token"

    Response.status = 302
    with pytest.raises(ValueError, match="redirect refused"):
        privileged_review._request_json("/repos/amattas/aviato", token="app-token")
    Response.status = 200
    monkeypatch.setenv("HTTPS_PROXY", "https://attacker.invalid")
    with pytest.raises(ValueError, match="proxy/TLS overrides"):
        privileged_review._request_json("/repos/amattas/aviato", token="app-token")
    monkeypatch.delenv("HTTPS_PROXY")
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/attacker-ca")
    with pytest.raises(ValueError, match="proxy/TLS overrides"):
        privileged_review._request_json("/repos/amattas/aviato", token="app-token")


def test_app_installation_identity_uses_full_pagination_and_exact_read_only_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aviato.plugins import privileged_review

    calls: list[str] = []
    permissions = copy.deepcopy(privileged_review._REQUIRED_APP_PERMISSIONS)

    def rest(path: str, *, token: str) -> object:
        assert token == "app-token"
        calls.append(path)
        if path == "/installation":
            return {
                "id": 20,
                "app_id": 10,
                "app_slug": "aviato-verifier",
                "permissions": permissions,
                "suspended_at": None,
            }
        if path.endswith("page=1"):
            return {"total_count": 101, "repositories": [{"id": item} for item in range(1, 101)]}
        if path.endswith("page=2"):
            return {"total_count": 101, "repositories": [{"id": 123}]}
        raise AssertionError(path)

    monkeypatch.setattr(privileged_review, "_rest", rest)
    authority = privileged_review._installation_authority(123, token="app-token")
    assert authority["repository_ids"][-1] == 123
    assert calls == [
        "/installation",
        "/installation/repositories?per_page=100&page=1",
        "/installation/repositories?per_page=100&page=2",
    ]
    permissions["contents"] = "write"
    with pytest.raises(ValueError, match="excess/write"):
        privileged_review._installation_authority(123, token="app-token")


def test_live_collector_reconstructs_complete_app_pr_review_ruleset_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aviato.plugins import privileged_review

    for name in privileged_review._DANGEROUS_NETWORK_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AVIATO_PRIVILEGED_REVIEW_TOKEN", "app-token")
    envelope = _envelope()
    policy = _policy()
    evidence = envelope["evidence"]
    protected = evidence["protected_files"]
    policy_body = json.dumps(policy).encode()
    codeowners = "\n".join(f"{item['path']} @reviewer-one @reviewer-two" for item in protected).encode()
    transcript: list[str] = []
    run_overrides: dict[str, Any] = {}
    branch_sha_override: list[str] = []
    workflow_body = b"name: Trusted review\n"

    def content(body: bytes, sha: str) -> dict[str, str]:
        return {"encoding": "base64", "content": base64.b64encode(body).decode(), "sha": sha}

    def rest(path: str, *, token: str) -> object:
        assert token == "app-token"
        transcript.append(path)
        if path == "/repos/amattas/aviato":
            return {"id": 123, "node_id": "R_aviato", "full_name": "amattas/aviato", "default_branch": "main"}
        if path == "/repos/amattas/aviato/pulls/99":
            return {
                "number": 99,
                "merged": True,
                "merge_commit_sha": "d" * 40,
                "base": {"sha": "a" * 40},
                "head": {"sha": "c" * 40},
                "user": {"id": 1, "login": "author"},
            }
        if path.endswith("/branches/main"):
            return {"commit": {"sha": branch_sha_override.pop(0) if branch_sha_override else "f" * 40}}
        if path.startswith("/repos/amattas/aviato/contents/aviato/library/privileged-review-policy.json"):
            return content(policy_body, "2" * 40 if "f" * 40 in path else "0" * 40)
        if path.startswith("/repos/amattas/aviato/contents/.github/CODEOWNERS"):
            return content(codeowners, "1" * 40)
        if path.startswith("/repos/amattas/aviato/contents/.github/workflows/aviato-privileged-review.yml"):
            return content(workflow_body, "e" * 40)
        if path == "/repos/amattas/aviato/actions/runs/500":
            run = {
                "id": 500,
                "path": ".github/workflows/aviato-privileged-review.yml",
                "head_branch": "main",
                "head_sha": "d" * 40,
                "event": "workflow_dispatch",
                "workflow_id": 501,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "repository": {"id": 123},
                "actor": {"id": 9, "login": "trusted-operator"},
                "triggering_actor": {"id": 9, "login": "trusted-operator"},
            }
            run.update(run_overrides)
            return run
        if path == "/repos/amattas/aviato/rulesets/17482301":
            return _ruleset_payload()
        if path == "/repos/amattas/aviato/environments/privileged-review":
            return {
                "name": "privileged-review",
                "can_admins_bypass": False,
                "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False},
                "protection_rules": [
                    {
                        "type": "required_reviewers",
                        "prevent_self_review": True,
                        "reviewers": [
                            {
                                "type": "User",
                                "reviewer": {"id": 2, "node_id": "U_2", "login": "reviewer-one"},
                            },
                            {
                                "type": "User",
                                "reviewer": {"id": 3, "node_id": "U_3", "login": "reviewer-two"},
                            },
                        ],
                    }
                ],
            }
        if path == "/installation":
            return {
                "id": 2001,
                "app_id": 1001,
                "app_slug": "aviato-verifier",
                "permissions": copy.deepcopy(privileged_review._REQUIRED_APP_PERMISSIONS),
                "suspended_at": None,
            }
        if path == "/installation/repositories?per_page=100&page=1":
            return {"total_count": 1, "repositories": [{"id": 123}]}
        raise AssertionError(path)

    def graph(repository: str, number: int, *, token: str) -> dict[str, Any]:
        assert (repository, number, token) == ("amattas/aviato", 99, "app-token")
        transcript.append("graphql:pull/reviews")
        nodes = []
        for review in evidence["reviews"]:
            nodes.append(
                {
                    "databaseId": review["review_id"],
                    "id": review["node_id"],
                    "state": "APPROVED",
                    "submittedAt": review["submitted_at"],
                    "lastEditedAt": None,
                    "dismissedAt": None,
                    "commit": {"oid": "c" * 40},
                    "author": {"databaseId": review["reviewer_database_id"], "login": review["reviewer_login"]},
                }
            )
        return {
            "headRefOid": "c" * 40,
            "commits": {"nodes": [{"commit": {"oid": "c" * 40, "pushedDate": "2026-07-15T13:00:00Z"}}]},
            "reviews": {"nodes": nodes},
        }

    def inventory(repository: str, sha: str, paths: list[str], *, token: str) -> list[dict[str, str]]:
        assert repository == "amattas/aviato" and token == "app-token" and paths == policy["protected_paths"]
        transcript.append(f"tree:{sha}")
        return [] if sha == "a" * 40 else copy.deepcopy(protected)

    monkeypatch.setattr(privileged_review, "_rest", rest)
    monkeypatch.setattr(privileged_review, "_pull_graph", graph)
    monkeypatch.setattr(privileged_review, "_tree_inventory", inventory)
    trusted, current, live = privileged_review.collect_live_privileged_review_evidence(envelope)
    assert trusted == policy
    assert current == policy
    assert live["collector"] == evidence["collector"]
    assert live["protected_files"] == protected
    assert live["reviews"] == evidence["reviews"]
    assert "/installation" in transcript and "graphql:pull/reviews" in transcript
    assert transcript.count("tree:" + "d" * 40) == 1
    assert live["workflow"]["blob_sha"] == "e" * 40
    assert live["workflow"]["blob_sha256"] == hashlib.sha256(b"name: Trusted review\n").hexdigest()

    for override in (
        {"event": "pull_request_target"},
        {"run_attempt": 0},
        {"status": "completed", "conclusion": "failure"},
        {"status": "completed", "conclusion": "cancelled"},
        {"status": "in_progress", "conclusion": None},
        {"actor": {"id": None, "login": "attacker"}},
    ):
        run_overrides.clear()
        run_overrides.update(override)
        with pytest.raises(ValueError, match="successful immutable run"):
            privileged_review.collect_live_privileged_review_evidence(envelope)

    run_overrides.clear()
    run_overrides.update({"status": "in_progress", "conclusion": None})
    _trusted, _current, predicted = privileged_review.collect_live_privileged_review_evidence(
        envelope, allow_in_progress_unsigned_collection=True
    )
    assert predicted["workflow"]["status"] == "completed"
    with pytest.raises(ValueError, match="successful immutable run"):
        privileged_review.collect_live_privileged_review_evidence({"evidence": predicted})
    run_overrides.clear()
    branch_sha_override.extend(["f" * 40, "0" * 40])
    with pytest.raises(ValueError, match="ref moved"):
        privileged_review.collect_live_privileged_review_evidence(envelope)


def test_trusted_workflow_has_bounded_default_branch_collect_verify_lifecycle() -> None:
    import yaml

    path = Path(".github/workflows/aviato-privileged-review.yml")
    assert path.is_file()
    document = yaml.safe_load(path.read_text())
    trigger = document.get("on", document.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"phase", "pull_request", "ruleset_id", "key_id", "key_version", "signed_envelope"}
    assert inputs["phase"]["type"] == "choice"
    assert inputs["phase"]["options"] == ["collect", "verify"]
    assert document["permissions"] == {"contents": "read", "actions": "read", "pull-requests": "read"}
    assert "concurrency" in document and document.get("run-name")
    source = path.read_text()
    assert "pull_request_target" not in source
    assert "github.event.repository.default_branch" in source
    assert "github.ref" in source
    assert "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5" in source
    assert "actions/create-github-app-token@fee1f7d63c2ff003460e3d139729b119787bc349" in source
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in source
    assert "ref: ${{ github.sha }}" in source
    assert "persist-credentials: false" in source
    assert "collect" in document["jobs"] and "verify" in document["jobs"]
    for job in document["jobs"].values():
        assert job["environment"] == "privileged-review"
        checkouts = [step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")]
        assert len(checkouts) == 1
        assert checkouts[0]["with"] == {"ref": "${{ github.sha }}", "persist-credentials": False}
    assert "AVIATO_PRIVILEGED_REVIEW_TOKEN" in source
    assert "AVIATO_PRIVILEGED_REVIEW_SIGNING" not in source
    assert 'test "${#SIGNED_ENVELOPE}" -le 60000' in source


@pytest.mark.parametrize(
    "mutation",
    (
        lambda w: w.update(blob_sha="0" * 40),
        lambda w: w.update(blob_sha256="0" * 64),
        lambda w: w.update(run_head_sha="0" * 40),
        lambda w: w.update(event="pull_request_target"),
        lambda w: w.update(run_attempt=0),
        lambda w: w.update(status="in_progress", conclusion=None),
        lambda w: w.update(conclusion="failure"),
        lambda w: w.update(actor_database_id=0),
    ),
)
def test_wrong_workflow_blob_run_event_attempt_status_and_actor_are_rejected(mutation: Any) -> None:
    envelope = _envelope()
    live = copy.deepcopy(envelope["evidence"])
    mutation(envelope["evidence"]["workflow"])
    assert _verify(envelope, live=live)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda e: e.update(can_admins_bypass=True),
        lambda e: e.update(prevent_self_review=False),
        lambda e: e.update(reviewers=e["reviewers"][:1]),
        lambda e: e.update(name="unprotected"),
        lambda e: e.update(deployment_branch_policy={"protected_branches": False, "custom_branch_policies": True}),
    ),
)
def test_unprotected_or_bypassable_privileged_review_environment_is_rejected(mutation: Any) -> None:
    envelope = _envelope()
    live = copy.deepcopy(envelope["evidence"])
    environment = envelope["evidence"]["environment"]
    mutation(environment)
    body = {key: value for key, value in environment.items() if key != "payload_sha256"}
    environment["payload_sha256"] = _digest(body)
    assert _verify(envelope, live=live)


def test_verify_cli_rejects_oversized_and_noncanonical_envelope_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from aviato.plugins import privileged_review

    output = tmp_path / "consumed.json"
    monkeypatch.setenv("AVIATO_PRIVILEGED_REVIEW_ENVELOPE_BASE64", "A" * 60_001)
    with pytest.raises(SystemExit):
        privileged_review.main(["verify", "--output", str(output)])
    raw = json.dumps(_envelope(), indent=2).encode()
    monkeypatch.setenv("AVIATO_PRIVILEGED_REVIEW_ENVELOPE_BASE64", base64.urlsafe_b64encode(raw).decode().rstrip("="))
    with pytest.raises(SystemExit):
        privileged_review.main(["verify", "--output", str(output)])


def test_offline_signer_uses_absolute_ssh_keygen_and_minimal_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from aviato.plugins import privileged_review

    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(_evidence(), sort_keys=True, separators=(",", ":")))
    key_path = tmp_path / "offline-key"
    key_path.write_text("private")
    signature_path = Path(str(evidence_path) + ".sig")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert command[0] == "/usr/bin/ssh-keygen"
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        signature_path.write_bytes(b"ssh signature")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    output = tmp_path / "envelope.json"
    privileged_review.sign_collected_evidence(evidence_path, key_path, output)
    envelope = json.loads(output.read_text())
    assert envelope["evidence"] == _evidence()
    assert base64.urlsafe_b64decode(envelope["signature"] + "==") == b"ssh signature"
    with pytest.raises(ValueError, match="already exists"):
        privileged_review.sign_collected_evidence(evidence_path, key_path, output)
    output.unlink()
    symlink_key = tmp_path / "symlink-key"
    symlink_key.symlink_to(key_path)
    with pytest.raises(ValueError, match="non-symlink"):
        privileged_review.sign_collected_evidence(evidence_path, symlink_key, output)


def test_each_privileged_cli_entrypoint_places_fresh_gate_before_platform_or_write() -> None:
    import inspect

    for command, write_marker in (
        (cli.cmd_apply_rulesets, "GitHubPlatform"),
        (cli.cmd_complete_protection, "GitHubPlatform"),
        (cli.cmd_provision, "GitHubPlatform"),
        (cli.cmd_reconcile, "run_reconcile"),
    ):
        source = inspect.getsource(command)
        assert source.index("_require_privileged_mutation_readiness") < source.index(write_marker)


def test_operational_gate_collects_live_again_on_every_invocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[Path] = []

    def ready(root: Path) -> bool:
        calls.append(root)
        return True

    monkeypatch.setattr(
        cli,
        "_require_privileged_mutation_readiness",
        ready,
    )
    cli._refresh_privileged_mutation_authority(tmp_path)
    cli._refresh_privileged_mutation_authority(tmp_path)
    assert calls == [tmp_path, tmp_path]


def test_generated_envelope_is_not_a_self_hash_but_all_mutable_authority_remains_protected() -> None:
    policy = json.loads(Path("aviato/library/privileged-review-policy.json").read_text())
    protected = policy["protected_paths"]
    assert "/aviato/library/privileged-review-attestation.json" not in protected
    for required in (
        "/.github/aviato-privileged-review.json",
        "/.github/workflows/",
        "/aviato/cli.py",
        "/aviato/plugins/privileged_review.py",
        "/aviato/plugins/release_mutations.py",
        "/MANIFEST.in",
        "/pyproject.toml",
        "/scripts/regen-privileged-execution-manifest.py",
    ):
        assert required in protected


def test_sdist_manifest_carries_the_trusted_lifecycle_sources() -> None:
    lines = set(Path("MANIFEST.in").read_text().splitlines())
    assert lines == {
        "include .github/CODEOWNERS",
        "include .github/aviato-privileged-review.json",
        "include .github/workflows/aviato-privileged-review.yml",
        "include scripts/regen-privileged-execution-manifest.py",
    }


def test_generator_inventory_detects_added_deleted_content_and_mode_drift(
    tmp_path: Path,
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location("regen_inventory", Path("scripts/regen-privileged-execution-manifest.py"))
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO_ROOT = tmp_path  # type: ignore[attr-defined]
    protected = tmp_path / "protected"
    protected.mkdir()
    first = protected / "first.py"
    first.write_text("one\n")
    baseline = module._local_protected_inventory(["/protected/"])
    first.write_text("two\n")
    assert module._local_protected_inventory(["/protected/"]) != baseline
    first.chmod(0o755)
    assert module._local_protected_inventory(["/protected/"])[0]["mode"] == "100755"
    (protected / "added.py").write_text("added\n")
    assert len(module._local_protected_inventory(["/protected/"])) == 2
    first.unlink()
    assert [item["path"] for item in module._local_protected_inventory(["/protected/"])] == ["/protected/added.py"]
