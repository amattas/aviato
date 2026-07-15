from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .command import DEFAULT_TIMEOUT_SECONDS, CommandError, run
from .core.ports import RepositoryIdentity
from .core.protection import (
    ReceiptPersistenceEvidence,
    canonical_authority_snapshot,
    sign_protection_receipt,
    verify_protection_receipt_envelope,
)
from .core.release_authorization import (
    CheckpointVerificationContext,
    ManagedReleaseCheckpoint,
    RegisteredReviewerKey,
    collect_checkpoint,
    persist_checkpoint_envelope,
    review_sign_envelope,
    verify_checkpoint_envelope,
)
from .github_platform import GitHubPlatform


def _gh_json(endpoint: str) -> Any:
    result = run(["gh", "api", "-H", "Cache-Control: no-cache", endpoint])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"GitHub response is not JSON for {endpoint}") from exc


def _gh_json_paginated(endpoint: str) -> list[Any]:
    result = run(["gh", "api", "--paginate", "--slurp", "-H", "Cache-Control: no-cache", endpoint])
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"GitHub paginated response is not JSON for {endpoint}") from exc
    return [item for page in pages if isinstance(page, list) for item in page] if isinstance(pages, list) else []


def _gh_json_input(method: str, endpoint: str, payload: dict[str, Any]) -> Any:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        path = Path(handle.name)
    try:
        result = run(["gh", "api", "--method", method, endpoint, "--input", str(path)])
    finally:
        path.unlink(missing_ok=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"GitHub write response is not JSON for {endpoint}") from exc


def _gh_graphql(query: str, variables: dict[str, Any]) -> Any:
    command = ["gh", "api", "graphql", "-H", "Cache-Control: no-cache", "-f", f"query={query}"]
    for name, value in variables.items():
        command.extend(["-F", f"{name}={value}"])
    result = run(command)
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("GitHub GraphQL response is not JSON") from exc
    if not isinstance(document, dict) or document.get("errors"):
        raise ValueError("GitHub GraphQL query failed")
    return document.get("data", document)


def _write_exclusive(path: Path, body: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(body)
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite checkpoint output: {path}") from exc


def _read_bounded(path: Path, *, maximum: int = 65_536) -> bytes:
    body = path.read_bytes()
    if not body or len(body) > maximum:
        raise ValueError(f"checkpoint input must contain 1..{maximum} bytes")
    return body


def _digest_json(value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(body).hexdigest()


def _collect_live_authority_snapshot(
    repository: str,
    repository_doc: dict[str, Any],
    *,
    default_branch: str,
    workflow_blob_sha: str,
    aviato_pin: str,
) -> dict[str, Any]:
    environments_doc = _gh_json(f"repos/{repository}/environments?per_page=100")
    environment_names = sorted(
        item["name"]
        for item in environments_doc.get("environments", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )
    live_state = GitHubPlatform().read_protection_state(
        repository, environments=tuple(environment_names), aviato_pin=aviato_pin
    )
    if repository == "amattas/aviato":
        release_ref = default_branch
        release_repository = repository
    else:
        release_ref = aviato_pin
        release_repository = "amattas/aviato"
    release_workflow = _gh_json(
        f"repos/{release_repository}/contents/.github/workflows/reusable-release.yml?ref={quote(release_ref, safe='')}"
    )
    release_blob_sha = release_workflow.get("sha")
    if not isinstance(release_blob_sha, str):
        raise ValueError("current reusable release workflow blob is unreadable")
    live_state["release_guard"] = {
        "repository": release_repository,
        "ref": release_ref,
        "path": ".github/workflows/reusable-release.yml",
        "blob_sha": release_blob_sha,
    }
    guard = live_state.get("guard")
    if guard is None or getattr(guard, "blob_sha", None) != workflow_blob_sha:
        raise ValueError("current intake guard blob differs from the source workflow")
    identity = RepositoryIdentity(
        database_id=repository_doc["id"],
        node_id=str(repository_doc.get("node_id") or ""),
        full_name=str(repository_doc.get("full_name") or ""),
        default_branch=default_branch,
    )
    return dict(canonical_authority_snapshot(repository=identity, live_state=live_state))


def _durable_receipt_authority_snapshot(repository: str, receipt_digest: str) -> dict[str, Any]:
    issues = _gh_json(f"repos/{repository}/issues?state=all&labels=aviato-protection-receipt&per_page=10")
    if not isinstance(issues, list) or len(issues) != 1 or type(issues[0].get("number")) is not int:
        raise ValueError("exactly one durable protection receipt issue is required")
    comments = _gh_json_paginated(f"repos/{repository}/issues/{issues[0]['number']}/comments?per_page=100")
    if comments and all(isinstance(page, list) for page in comments):
        comments = [item for page in comments for item in page]
    marker = "Canonical `aviato-protection-receipt-envelope/v1` evidence:\n\n```json\n"
    matches: list[dict[str, Any]] = []
    for comment in comments if isinstance(comments, list) else ():
        body = comment.get("body") if isinstance(comment, dict) else None
        if not isinstance(body, str) or not body.startswith(marker) or not body.endswith("\n```"):
            continue
        try:
            envelope_bytes = body[len(marker) : -4].encode("ascii")
            envelope = json.loads(envelope_bytes)
            receipt_bytes = base64.urlsafe_b64decode(
                str(envelope["receipt_base64url"]) + "=" * (-len(str(envelope["receipt_base64url"])) % 4)
            )
            receipt = json.loads(receipt_bytes)
        except (KeyError, UnicodeEncodeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("durable protection receipt comment is malformed") from exc
        if hashlib.sha256(receipt_bytes).hexdigest() == receipt_digest:
            canonical_receipt = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "ascii"
            )
            if receipt_bytes != canonical_receipt:
                raise ValueError("durable protection receipt bytes are not canonical")
            matches.append(receipt)
    if len(matches) != 1:
        raise ValueError("protection receipt digest did not select exactly one durable receipt")
    receipt = matches[0]
    snapshot = receipt.get("authority_snapshot")
    if (
        receipt.get("schema") != "aviato-protection-receipt/v1"
        or receipt.get("status") != "ready"
        or receipt.get("persistence_status") != "attached"
        or not isinstance(snapshot, dict)
    ):
        raise ValueError("durable protection receipt is not ready canonical authority")
    return snapshot


def collect_live_checkpoint(
    *,
    repository: str,
    tag: str,
    sha: str,
    intended_actor: str,
    reviewer: str,
    submitter: str,
    pin: str,
    snapshot_sha: str,
    protection_plan_id: str,
    protection_receipt_digest: str,
    workflow_path: str,
    source_run_id: int,
    ttl_seconds: int,
    output: Path,
) -> ManagedReleaseCheckpoint:
    """Collect redacted live evidence with the operator's current gh credential."""

    repository_doc = _gh_json(f"repos/{repository}")
    collector_doc = _gh_json("user")
    default_branch = repository_doc.get("default_branch")
    workflow = _gh_json(
        f"repos/{repository}/contents/{quote(workflow_path, safe='/')}?ref={quote(str(default_branch), safe='')}"
    )
    source_run = _gh_json(f"repos/{repository}/actions/runs/{source_run_id}")
    if (
        not isinstance(repository_doc.get("id"), int)
        or not isinstance(collector_doc.get("login"), str)
        or not isinstance(default_branch, str)
        or not isinstance(workflow.get("sha"), str)
        or source_run.get("head_sha") != sha
        or source_run.get("head_branch") != default_branch
        or source_run.get("status") != "completed"
        or source_run.get("conclusion") != "success"
    ):
        raise ValueError("current repository/workflow/source-run evidence is incomplete or mismatched")
    issued_at = int(time.time())
    authority_snapshot = _collect_live_authority_snapshot(
        repository,
        repository_doc,
        default_branch=default_branch,
        workflow_blob_sha=workflow["sha"],
        aviato_pin=pin,
    )
    receipt_snapshot = _durable_receipt_authority_snapshot(repository, protection_receipt_digest)
    if authority_snapshot != receipt_snapshot:
        raise ValueError("current canonical authority snapshot differs from the durable protection receipt")
    checkpoint = ManagedReleaseCheckpoint(
        repository_id=repository_doc["id"],
        repository=repository,
        tag=tag,
        sha=sha,
        intended_actor=intended_actor,
        collector=collector_doc["login"],
        reviewer=reviewer,
        submitter=submitter,
        pin=pin,
        snapshot_sha=snapshot_sha,
        protection_plan_id=protection_plan_id,
        protection_receipt_digest=protection_receipt_digest,
        authority_snapshot=authority_snapshot,
        workflow_path=workflow_path,
        workflow_blob_sha=workflow["sha"],
        workflow_ref=f"refs/heads/{default_branch}",
        workflow_run_id=source_run_id,
        issued_at=issued_at,
        expires_at=issued_at + ttl_seconds,
    )
    _write_exclusive(output, collect_checkpoint(checkpoint, credential_present=True))
    return checkpoint


def ssh_sign_exact(message: bytes, *, signing_key: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="aviato-checkpoint-sign-") as directory:
        message_path = Path(directory) / "checkpoint"
        message_path.write_bytes(message)
        run(["ssh-keygen", "-Y", "sign", "-f", str(signing_key), "-n", "aviato", str(message_path)])
        signature_path = Path(str(message_path) + ".sig")
        signature = signature_path.read_bytes()
        if not signature:
            raise ValueError("ssh-keygen produced an empty checkpoint signature")
        return signature


def review_sign_file(
    *,
    input_path: Path,
    output: Path,
    reviewer: str,
    collector: str,
    key_id: str,
    signing_key: Path,
) -> bytes:
    unsigned = _read_bounded(input_path)
    envelope = review_sign_envelope(
        unsigned,
        reviewer=reviewer,
        collector=collector,
        key_id=key_id,
        signer=lambda message: ssh_sign_exact(message, signing_key=signing_key),
    )
    _write_exclusive(output, envelope)
    return envelope


def _verify_ssh_signature(public_key: bytes, message: bytes, signature: bytes, *, reviewer: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="aviato-checkpoint-verify-") as directory:
        root = Path(directory)
        allowed = root / "allowed_signers"
        signature_path = root / "signature"
        allowed.write_bytes(reviewer.encode("utf-8") + b" " + public_key.rstrip(b"\n") + b"\n")
        signature_path.write_bytes(signature)
        try:
            result = subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed),
                    "-I",
                    reviewer,
                    "-n",
                    "aviato",
                    "-s",
                    str(signature_path),
                ],
                input=message,
                capture_output=True,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CommandError(["ssh-keygen", "-Y", "verify"], 127, str(exc)) from exc
        return result.returncode == 0


def verify_live_checkpoint(*, input_path: Path, output: Path | None = None) -> ManagedReleaseCheckpoint:
    raw = _read_bounded(input_path)
    parsed = json.loads(raw)
    document = parsed.get("checkpoint") if isinstance(parsed, dict) else None
    if not isinstance(document, dict):
        raise ValueError("checkpoint envelope omitted its document")
    repository = document.get("repository")
    reviewer = document.get("reviewer")
    if not isinstance(repository, str) or not isinstance(reviewer, str):
        raise ValueError("checkpoint envelope omitted repository/reviewer identity")
    repository_doc = _gh_json(f"repos/{repository}")
    permission = _gh_json(f"repos/{repository}/collaborators/{reviewer}/permission")
    workflow_path = document.get("workflow_path")
    default_branch = repository_doc.get("default_branch")
    workflow = _gh_json(
        f"repos/{repository}/contents/{quote(str(workflow_path), safe='/')}?ref={quote(str(default_branch), safe='')}"
    )
    source_run = _gh_json(f"repos/{repository}/actions/runs/{document.get('workflow_run_id')}")
    keys = _gh_json(f"users/{reviewer}/ssh_signing_keys")
    selected = [item for item in keys if str(item.get("id")) == str(parsed.get("key_id"))]
    if len(selected) != 1 or not isinstance(selected[0].get("key"), str):
        raise ValueError("checkpoint reviewer key is not one current concrete GitHub signing key")
    intended_actor = document.get("intended_actor")
    submitter = document.get("submitter")
    workflow_run_id = document.get("workflow_run_id")
    protection_plan_id = document.get("protection_plan_id")
    protection_receipt_digest = document.get("protection_receipt_digest")
    authority_snapshot = document.get("authority_snapshot")
    if (
        not isinstance(intended_actor, str)
        or not isinstance(submitter, str)
        or type(workflow_run_id) is not int
        or not isinstance(protection_plan_id, str)
        or not isinstance(protection_receipt_digest, str)
        or not isinstance(authority_snapshot, dict)
    ):
        raise ValueError("checkpoint envelope contains malformed live-verification fields")
    current_snapshot = _collect_live_authority_snapshot(
        repository,
        repository_doc,
        default_branch=str(default_branch),
        workflow_blob_sha=str(workflow.get("sha") or ""),
        aviato_pin=str(document.get("pin") or ""),
    )
    context = CheckpointVerificationContext(
        repository_id=repository_doc.get("id"),
        repository=repository,
        intended_actor=intended_actor,
        submitter=submitter,
        reviewer=reviewer,
        reviewer_kind=permission.get("user", {}).get("type", ""),
        reviewer_database_id=permission.get("user", {}).get("id"),
        reviewer_is_admin=permission.get("permission") == "admin",
        workflow_path=str(workflow_path),
        workflow_blob_sha=workflow.get("sha"),
        workflow_ref=f"refs/heads/{default_branch}",
        workflow_run_id=workflow_run_id,
        source_sha=source_run.get("head_sha"),
        protection_plan_id=protection_plan_id,
        protection_receipt_digest=protection_receipt_digest,
        authority_snapshot=current_snapshot,
    )
    key = RegisteredReviewerKey(
        key_id=str(parsed["key_id"]),
        reviewer=reviewer,
        public_key=selected[0]["key"].encode("utf-8"),
        current=True,
    )
    verified = verify_checkpoint_envelope(
        raw,
        context=context,
        resolve_key=lambda key_id: key if key_id == key.key_id else None,
        verify_signature=lambda public_key, message, signature: _verify_ssh_signature(
            public_key, message, signature, reviewer=reviewer
        ),
        now=int(time.time()),
    )
    if output is not None:
        _write_exclusive(output, raw)
    return verified


def persist_verified_checkpoint(*, input_path: Path, repository: str) -> str:
    raw = _read_bounded(input_path)
    checkpoint = verify_live_checkpoint(input_path=input_path)

    def dispatch(envelope: bytes) -> None:
        encoded = base64.urlsafe_b64encode(envelope).decode("ascii").rstrip("=")
        branch = _gh_json(f"repos/{repository}").get("default_branch")
        run(
            [
                "gh",
                "workflow",
                "run",
                "aviato-protection-checkpoint.yml",
                "--repo",
                repository,
                "--ref",
                str(branch),
                "-f",
                f"checkpoint-base64url={encoded}",
            ]
        )

    return persist_checkpoint_envelope(raw, checkpoint=checkpoint, persist=dispatch)


def persist_signed_protection_receipt(
    *,
    repository: str,
    canonical_receipt: bytes,
    principal: str,
    key_id: str,
    signing_key: Path,
) -> ReceiptPersistenceEvidence:
    """SSH-sign exact receipt bytes, append one immutable issue comment, and read it back."""

    envelope = sign_protection_receipt(
        canonical_receipt,
        principal=principal,
        key_id=key_id,
        signer=lambda message: ssh_sign_exact(message, signing_key=signing_key),
    )
    issues = _gh_json(f"repos/{repository}/issues?state=all&labels=aviato-protection-receipt&per_page=10")
    if not isinstance(issues, list) or len(issues) > 1:
        raise ValueError("receipt tracking issue is unreadable or ambiguous")
    if issues:
        issue = issues[0]
    else:
        issue = _gh_json_input(
            "POST",
            f"repos/{repository}/issues",
            {
                "title": "Aviato composite protection receipts",
                "body": (
                    "Immutable SSH-signed receipt envelopes are appended as comments; this issue body is not authority."
                ),
                "labels": ["aviato-protection-receipt"],
            },
        )
    if not isinstance(issue, dict) or type(issue.get("number")) is not int or not issue.get("node_id"):
        raise ValueError("receipt tracking issue omitted immutable identity")
    comment = _gh_json_input(
        "POST",
        f"repos/{repository}/issues/{issue['number']}/comments",
        {
            "body": "Canonical `aviato-protection-receipt-envelope/v1` evidence:\n\n```json\n"
            + envelope.decode("ascii")
            + "\n```"
        },
    )
    if not isinstance(comment, dict) or type(comment.get("id")) is not int or not comment.get("node_id"):
        raise ValueError("receipt comment response omitted immutable identity")
    readback = _gh_json(f"repos/{repository}/issues/comments/{comment['id']}")
    author = readback.get("user") if isinstance(readback, dict) else None
    if not isinstance(author, dict) or author.get("login") != principal or type(author.get("id")) is not int:
        raise ValueError("receipt comment author differs from preview-bound principal")
    permission = _gh_json(f"repos/{repository}/collaborators/{quote(principal, safe='')}/permission")
    keys = _gh_json(f"users/{quote(principal, safe='')}/ssh_signing_keys")
    selected = [item for item in keys if str(item.get("id")) == key_id] if isinstance(keys, list) else []
    if len(selected) != 1 or not isinstance(selected[0].get("key"), str):
        raise ValueError("receipt signing key is absent, replaced, or revoked")
    if permission.get("permission") != "admin" or permission.get("user", {}).get("type") != "User":
        raise ValueError("receipt author is not a current concrete repository admin")
    verify_protection_receipt_envelope(
        envelope,
        expected_receipt=canonical_receipt,
        expected_principal=principal,
        expected_key_id=key_id,
        verify_signature=lambda message, signature: _verify_ssh_signature(
            selected[0]["key"].encode("utf-8"), message, signature, reviewer=principal
        ),
    )
    expected_body = (
        "Canonical `aviato-protection-receipt-envelope/v1` evidence:\n\n```json\n" + envelope.decode("ascii") + "\n```"
    )
    if (
        readback.get("node_id") != comment["node_id"]
        or readback.get("body") != expected_body
        or readback.get("created_at") != readback.get("updated_at")
    ):
        raise ValueError("receipt comment was edited, replaced, or did not read back exactly")
    graph = _gh_graphql(
        """query($id: ID!) {
          node(id: $id) {
            __typename
            ... on IssueComment {
              id databaseId body createdAt lastEditedAt isMinimized
              author { __typename login ... on User { databaseId } }
              issue { id }
            }
          }
        }""",
        {"id": str(comment["node_id"])},
    )
    node = graph.get("node") if isinstance(graph, dict) else None
    graph_author = node.get("author") if isinstance(node, dict) else None
    graph_issue = node.get("issue") if isinstance(node, dict) else None
    if (
        not isinstance(node, dict)
        or node.get("__typename") != "IssueComment"
        or node.get("id") != comment["node_id"]
        or node.get("databaseId") != comment["id"]
        or node.get("body") != expected_body
        or not node.get("createdAt")
        or node.get("lastEditedAt") is not None
        or node.get("isMinimized") is not False
        or not isinstance(graph_author, dict)
        or graph_author.get("__typename") != "User"
        or graph_author.get("login") != principal
        or graph_author.get("databaseId") != author["id"]
        or not isinstance(graph_issue, dict)
        or graph_issue.get("id") != issue["node_id"]
    ):
        raise ValueError("GraphQL IssueComment readback was edited, minimized, deleted, or replaced")
    return ReceiptPersistenceEvidence(
        envelope=envelope,
        issue_node_id=str(graph_issue["id"]),
        comment_node_id=str(node["id"]),
        source_comment_node_id=str(node["id"]),
        comment_database_id=node["databaseId"],
        author=principal,
        author_database_id=graph_author["databaseId"],
        author_is_admin=True,
        key_id=key_id,
        key_current=True,
        created_at=str(node["createdAt"]),
        last_edited_at=node["lastEditedAt"],
        is_minimized=node["isMinimized"],
    )


def resolve_receipt_signing_identity(*, repository: str, principal: str, key_id: str) -> dict[str, str]:
    permission = _gh_json(f"repos/{repository}/collaborators/{quote(principal, safe='')}/permission")
    keys = _gh_json(f"users/{quote(principal, safe='')}/ssh_signing_keys")
    selected = [item for item in keys if str(item.get("id")) == key_id] if isinstance(keys, list) else []
    if (
        permission.get("permission") != "admin"
        or permission.get("user", {}).get("type") != "User"
        or len(selected) != 1
        or not isinstance(selected[0].get("key"), str)
    ):
        raise ValueError("receipt signer must be one current concrete admin with one current GitHub signing key")
    public_key = selected[0]["key"].encode("utf-8")
    return {
        "principal": principal,
        "key_id": key_id,
        "public_key_fingerprint": hashlib.sha256(public_key).hexdigest(),
    }
