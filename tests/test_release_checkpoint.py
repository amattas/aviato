from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any

import pytest


def _module() -> Any:
    return importlib.import_module("aviato.release_checkpoint")


def test_collector_has_no_arbitrary_caller_fingerprint_input() -> None:
    assert "fingerprints" not in inspect.signature(_module().collect_live_checkpoint).parameters


def test_durable_receipt_selection_finds_page_two_and_rejects_duplicate_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    receipt = {
        "schema": "aviato-protection-receipt/v1",
        "status": "ready",
        "persistence_status": "attached",
        "authority_snapshot": {"schema": "aviato-protection-authority-snapshot/v1"},
    }
    raw = __import__("json").dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    digest = __import__("hashlib").sha256(raw).hexdigest()
    envelope = {"receipt_base64url": __import__("base64").urlsafe_b64encode(raw).decode().rstrip("=")}
    body = (
        "Canonical `aviato-protection-receipt-envelope/v1` evidence:\n\n```json\n"
        + __import__("json").dumps(envelope)
        + "\n```"
    )
    monkeypatch.setattr(module, "_gh_json", lambda *_args, **_kwargs: [{"number": 3}])
    pages = [[{"body": "unrelated"}] * 100, [{"body": body}]]
    monkeypatch.setattr(module, "_gh_json_paginated", lambda *_args, **_kwargs: pages, raising=False)
    assert module._durable_receipt_authority_snapshot("o/r", digest)["schema"].endswith("/v1")
    pages[0][0] = {"body": body}
    with pytest.raises(ValueError, match="exactly one"):
        module._durable_receipt_authority_snapshot("o/r", digest)


def test_receipt_persistence_is_derived_from_exact_graphql_issue_comment_readback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    canonical_receipt = b'{"schema":"aviato-protection-receipt/v1"}'
    envelope = b'{"schema":"aviato-protection-receipt-envelope/v1"}'
    expected_body = (
        "Canonical `aviato-protection-receipt-envelope/v1` evidence:\n\n```json\n" + envelope.decode("ascii") + "\n```"
    )
    graphql_calls: list[tuple[str, dict[str, Any]]] = []

    monkeypatch.setattr(module, "sign_protection_receipt", lambda *_args, **_kwargs: envelope)
    monkeypatch.setattr(module, "verify_protection_receipt_envelope", lambda *_args, **_kwargs: canonical_receipt)
    monkeypatch.setattr(module, "_verify_ssh_signature", lambda *_args, **_kwargs: True)

    def gh_json(endpoint: str) -> Any:
        if endpoint.endswith("issues?state=all&labels=aviato-protection-receipt&per_page=10"):
            return [{"number": 3, "node_id": "I_1"}]
        if endpoint == "repos/o/r/issues/comments/44":
            return {
                "id": 44,
                "node_id": "IC_1",
                "body": expected_body,
                "created_at": "2026-07-15T00:00:00Z",
                "updated_at": "2026-07-15T00:00:00Z",
                "user": {"login": "alice", "id": 11, "type": "User"},
            }
        if endpoint == "repos/o/r/collaborators/alice/permission":
            return {"permission": "admin", "user": {"login": "alice", "id": 11, "type": "User"}}
        if endpoint == "users/alice/ssh_signing_keys":
            return [{"id": "key-1", "key": "ssh-ed25519 AAAA"}]
        raise AssertionError(endpoint)

    monkeypatch.setattr(module, "_gh_json", gh_json)
    monkeypatch.setattr(
        module,
        "_gh_json_input",
        lambda *_args, **_kwargs: {"id": 44, "node_id": "IC_1"},
    )

    def graphql(query: str, variables: dict[str, Any]) -> Any:
        graphql_calls.append((query, variables))
        return {
            "node": {
                "__typename": "IssueComment",
                "id": "IC_1",
                "databaseId": 44,
                "body": expected_body,
                "createdAt": "2026-07-15T00:00:00Z",
                "lastEditedAt": None,
                "isMinimized": False,
                "author": {"__typename": "User", "login": "alice", "databaseId": 11},
                "issue": {"id": "I_1"},
            }
        }

    monkeypatch.setattr(module, "_gh_graphql", graphql, raising=False)

    evidence = module.persist_signed_protection_receipt(
        repository="o/r",
        canonical_receipt=canonical_receipt,
        principal="alice",
        key_id="key-1",
        signing_key=tmp_path / "key",
    )

    assert graphql_calls and graphql_calls[0][1] == {"id": "IC_1"}
    assert evidence.comment_node_id == "IC_1"
    assert evidence.issue_node_id == "I_1"
    assert evidence.comment_database_id == 44
    assert evidence.source_comment_node_id == "IC_1"
    assert evidence.is_minimized is False
    assert not hasattr(evidence, "event_node_id")


@pytest.mark.parametrize(
    "mutation",
    (
        {"lastEditedAt": "2026-07-15T00:01:00Z"},
        {"isMinimized": True},
        {"body": "replacement"},
        {"author": None},
        {"issue": {"id": "I_replaced"}},
    ),
)
def test_receipt_persistence_rejects_edited_minimized_replaced_or_deleted_graphql_comment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: dict[str, Any]
) -> None:
    module = _module()
    canonical_receipt = b'{"schema":"aviato-protection-receipt/v1"}'
    envelope = b'{"schema":"aviato-protection-receipt-envelope/v1"}'
    expected_body = (
        "Canonical `aviato-protection-receipt-envelope/v1` evidence:\n\n```json\n" + envelope.decode("ascii") + "\n```"
    )
    node: dict[str, Any] = {
        "__typename": "IssueComment",
        "id": "IC_1",
        "databaseId": 44,
        "body": expected_body,
        "createdAt": "2026-07-15T00:00:00Z",
        "lastEditedAt": None,
        "isMinimized": False,
        "author": {"__typename": "User", "login": "alice", "databaseId": 11},
        "issue": {"id": "I_1"},
    }
    node.update(mutation)
    monkeypatch.setattr(module, "sign_protection_receipt", lambda *_args, **_kwargs: envelope)
    monkeypatch.setattr(module, "verify_protection_receipt_envelope", lambda *_args, **_kwargs: canonical_receipt)
    monkeypatch.setattr(module, "_verify_ssh_signature", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        module,
        "_gh_json_input",
        lambda *_args, **_kwargs: {"id": 44, "node_id": "IC_1"},
    )

    def gh_json(endpoint: str) -> Any:
        if "issues?state=all" in endpoint:
            return [{"number": 3, "node_id": "I_1"}]
        if endpoint.endswith("issues/comments/44"):
            return {
                "id": 44,
                "node_id": "IC_1",
                "body": expected_body,
                "created_at": "2026-07-15T00:00:00Z",
                "updated_at": "2026-07-15T00:00:00Z",
                "user": {"login": "alice", "id": 11, "type": "User"},
            }
        if "collaborators" in endpoint:
            return {"permission": "admin", "user": {"type": "User"}}
        if "ssh_signing_keys" in endpoint:
            return [{"id": "key-1", "key": "ssh-ed25519 AAAA"}]
        raise AssertionError(endpoint)

    monkeypatch.setattr(module, "_gh_json", gh_json)
    monkeypatch.setattr(module, "_gh_graphql", lambda *_args, **_kwargs: {"node": node}, raising=False)

    with pytest.raises(ValueError, match="GraphQL|comment"):
        module.persist_signed_protection_receipt(
            repository="o/r",
            canonical_receipt=canonical_receipt,
            principal="alice",
            key_id="key-1",
            signing_key=tmp_path / "key",
        )
