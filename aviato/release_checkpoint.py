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
from .core.protection import (
    ReceiptPersistenceEvidence,
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


def _gh_json(endpoint: str) -> Any:
    result = run(["gh", "api", "-H", "Cache-Control: no-cache", endpoint])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"GitHub response is not JSON for {endpoint}") from exc


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


def _fingerprints(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--fingerprint requires NAME=SHA256")
        name, digest = value.split("=", 1)
        if not name or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("--fingerprint requires NAME=SHA256")
        if name in result:
            raise ValueError(f"duplicate checkpoint fingerprint {name!r}")
        result[name] = digest
    if not result:
        raise ValueError("at least one current protection fingerprint is required")
    return result


def _digest_json(value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(body).hexdigest()


def _collect_live_authority_fingerprints(
    repository: str,
    repository_doc: dict[str, Any],
    *,
    default_branch: str,
    workflow_blob_sha: str,
    aviato_pin: str,
) -> dict[str, str]:
    classic = _gh_json(f"repos/{repository}/branches/{quote(default_branch, safe='')}/protection")
    listed_rulesets = _gh_json(f"repos/{repository}/rulesets?includes_parents=false&per_page=100")
    if not isinstance(listed_rulesets, list):
        raise ValueError("current ruleset inventory is unreadable")
    rulesets = [
        _gh_json(f"repos/{repository}/rulesets/{item['id']}")
        for item in listed_rulesets
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    ]
    if len(rulesets) != len(listed_rulesets):
        raise ValueError("current ruleset inventory omitted immutable IDs")
    environments_doc = _gh_json(f"repos/{repository}/environments?per_page=100")
    environment_names = sorted(
        item["name"]
        for item in environments_doc.get("environments", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )
    environments = {
        name: _gh_json(f"repos/{repository}/environments/{quote(name, safe='')}") for name in environment_names
    }
    repository_surface = {
        key: repository_doc.get(key)
        for key in (
            "id",
            "node_id",
            "full_name",
            "default_branch",
            "allow_merge_commit",
            "allow_squash_merge",
            "allow_rebase_merge",
            "delete_branch_on_merge",
        )
    }
    security_surface = repository_doc.get("security_and_analysis")
    merge_surface = {key: value for key, value in repository_surface.items() if key.startswith("allow_")}
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
    fingerprints = {
        "live:classic": _digest_json(classic),
        "live:repository": _digest_json(repository_surface),
        "live:security": _digest_json(security_surface),
        "live:merge": _digest_json(merge_surface),
        "live:rulesets": _digest_json(sorted(rulesets, key=lambda item: item["id"])),
        "live:guard": _digest_json(
            {
                "intake_path": ".github/workflows/aviato-protection-checkpoint.yml",
                "intake_blob_sha": workflow_blob_sha,
                "release_repository": release_repository,
                "release_path": ".github/workflows/reusable-release.yml",
                "release_ref": release_ref,
                "release_blob_sha": release_blob_sha,
            }
        ),
        "live:checks": _digest_json(classic.get("required_status_checks") if isinstance(classic, dict) else None),
        "live:environments": _digest_json(environments),
    }
    for name, environment in environments.items():
        fingerprints[f"live:environment:{name}"] = _digest_json(environment)
    return fingerprints


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
    fingerprints: list[str],
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
    supplied_fingerprints = _fingerprints(fingerprints)
    live_fingerprints = _collect_live_authority_fingerprints(
        repository,
        repository_doc,
        default_branch=default_branch,
        workflow_blob_sha=workflow["sha"],
        aviato_pin=pin,
    )
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
        fingerprints={**supplied_fingerprints, **live_fingerprints},
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
    fingerprints = document.get("fingerprints")
    if (
        not isinstance(intended_actor, str)
        or not isinstance(submitter, str)
        or type(workflow_run_id) is not int
        or not isinstance(protection_plan_id, str)
        or not isinstance(protection_receipt_digest, str)
        or not isinstance(fingerprints, dict)
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in fingerprints.items())
    ):
        raise ValueError("checkpoint envelope contains malformed live-verification fields")
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
        fingerprints=fingerprints,
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
    return ReceiptPersistenceEvidence(
        envelope=envelope,
        issue_node_id=str(issue["node_id"]),
        comment_node_id=str(comment["node_id"]),
        event_node_id=str(comment["node_id"]),
        comment_database_id=comment["id"],
        author=principal,
        author_database_id=author["id"],
        author_is_admin=True,
        key_id=key_id,
        key_current=True,
        created_at=str(readback.get("created_at") or ""),
        last_edited_at=None,
        deleted=False,
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
