"""Standalone, stdlib-only final release-authority verifier.

This file is fetched by its checkpoint-bound Git blob SHA; it deliberately has no
imports from the installed Aviato package or consumer checkout.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import pathlib
import ssl
import subprocess
import tempfile
import time
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlsplit

AUTHORITY_SNAPSHOT_SCHEMA = "aviato-protection-authority-snapshot/v1"
JsonReader = Callable[[str, bool], Any]


class DenyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Fail closed instead of forwarding the verifier token across redirects."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _system_ssl_context() -> ssl.SSLContext:
    """Load platform trust roots while ignoring attacker-controlled OpenSSL env."""

    removed = {key: os.environ.pop(key) for key in ("SSL_CERT_FILE", "SSL_CERT_DIR") if key in os.environ}
    try:
        return ssl.create_default_context()
    finally:
        os.environ.update(removed)


def _github_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=_system_ssl_context()),
        DenyRedirectHandler(),
    )


def _is_github_api_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.netloc == "api.github.com" and parsed.path.startswith("/")


def flatten_paginated_pages(pages: object, collection_key: str | None) -> list[Any]:
    result: list[Any] = []
    for page in pages if isinstance(pages, list) else ():
        values = page.get(collection_key, ()) if collection_key and isinstance(page, dict) else page
        if isinstance(values, list):
            result.extend(values)
    return result


def select_unique_signing_key(pages: object, key_id: str) -> dict[str, Any]:
    """Select one exact current signing key from a fully paginated response."""

    selected = [
        item
        for item in flatten_paginated_pages(pages, None)
        if isinstance(item, dict) and str(item.get("id")) == str(key_id)
    ]
    if len(selected) != 1 or not isinstance(selected[0].get("key"), str):
        raise ValueError("signing key id must select exactly one current key")
    return selected[0]


def git_blob_sha(body: bytes) -> str:
    """Return Git's object ID for one blob, binding bytes rather than API metadata."""

    framed = b"blob " + str(len(body)).encode("ascii") + b"\0" + body
    return hashlib.sha1(framed).hexdigest()


def decode_contents_payload(payload: dict[str, Any], *, max_bytes: int) -> bytes:
    """Decode GitHub Contents API bytes without accepting generic whitespace."""

    content = payload.get("content")
    if payload.get("encoding") != "base64" or not isinstance(content, str):
        raise ValueError("verifier content encoding is not base64")
    if any(character.isspace() and character not in "\r\n" for character in content):
        raise ValueError("verifier content contains forbidden whitespace")
    encoded = content.replace("\r", "").replace("\n", "")
    if len(encoded) > ((max_bytes + 2) // 3) * 4:
        raise ValueError("verifier content is too large")
    try:
        body = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("verifier content is invalid base64") from exc
    if not 1 <= len(body) <= max_bytes:
        raise ValueError("verifier content is too large")
    if payload.get("sha") != git_blob_sha(body):
        raise ValueError("verifier content Git blob SHA mismatch")
    return body


def project_authority_snapshot(repository: dict[str, Any], live_state: dict[str, Any]) -> dict[str, Any]:
    """The one canonical projection used by receipt creation and fresh verification."""

    rulesets = sorted(
        (dict(item) for item in live_state.get("rulesets", ()) if isinstance(item, dict)),
        key=lambda item: (item.get("id") is None, item.get("id"), json.dumps(item, sort_keys=True)),
    )
    checks = [dict(item) for item in live_state.get("required_checks", ()) if isinstance(item, dict)]
    checks.sort(
        key=lambda item: (
            str(item.get("context", "")),
            str(item.get("app_id", "")),
            str(item.get("integration_id", "")),
            str(item.get("source", "")),
        )
    )
    return {
        "schema": AUTHORITY_SNAPSHOT_SCHEMA,
        "repository": repository,
        "classic": live_state.get("classic", {}),
        "repository_settings": live_state.get("repository", {}),
        "security": live_state.get("security", {}),
        "merge": live_state.get("merge", {}),
        "rulesets": rulesets,
        "environments": dict(sorted((live_state.get("environments") or {}).items())),
        "required_checks": checks,
        "guard": {
            "intake": live_state.get("guard"),
            "release": live_state.get("release_guard"),
            "verifier": live_state.get("verifier_guard"),
        },
    }


def _gh(endpoint: str, paginated: bool = False) -> Any:
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN is required for authority verification")
    url: str | None = f"https://api.github.com/{endpoint.lstrip('/')}"
    pages: list[Any] = []
    opener = _github_opener()
    while url:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Cache-Control": "no-cache",
                "User-Agent": "aviato-authority-verifier",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with opener.open(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API origin
            if not _is_github_api_url(response.geturl()):
                raise RuntimeError("GitHub API response escaped the exact HTTPS origin")
            pages.append(json.loads(response.read()))
            link = response.headers.get("Link", "")
        next_url = None
        if paginated:
            for item in link.split(","):
                if 'rel="next"' in item:
                    candidate = item.split(";", 1)[0].strip()
                    if candidate.startswith("<") and candidate.endswith(">") and _is_github_api_url(candidate[1:-1]):
                        next_url = candidate[1:-1]
                    else:
                        raise RuntimeError("GitHub pagination escaped the API origin")
        url = next_url
    return pages if paginated else pages[0]


def verify_ssh_signature(message: bytes, signature: bytes, reviewer: str, public_key: str) -> None:
    """Verify a checkpoint signature without PATH lookup or ambient secrets."""

    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        (root / "allowed").write_text(f"{reviewer} {public_key}\n")
        (root / "signature").write_bytes(signature)
        result = subprocess.run(
            [
                "/usr/bin/ssh-keygen",
                "-Y",
                "verify",
                "-f",
                str(root / "allowed"),
                "-I",
                reviewer,
                "-n",
                "aviato",
                "-s",
                str(root / "signature"),
            ],
            input=message,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
        if result.returncode:
            raise ValueError("checkpoint SSH signature is invalid")


def _classic(rules: list[dict[str, Any]], protection: dict[str, Any]) -> dict[str, Any]:
    pr = next((rule for rule in rules if rule.get("type") == "pull_request"), None)
    params = (pr.get("parameters") or {}) if pr else {}
    reviews = protection.get("required_pull_request_reviews") or {}
    checks = protection.get("required_status_checks") or {}
    contexts = list(checks.get("contexts") or ())
    contexts += [item.get("context") for item in checks.get("checks") or () if item.get("context")]
    for rule in rules:
        if rule.get("type") == "required_status_checks":
            contexts += [
                item.get("context")
                for item in (rule.get("parameters") or {}).get("required_status_checks") or ()
                if item.get("context")
            ]
    classic_admin = bool((protection.get("enforce_admins") or {}).get("enabled"))
    allow_force = protection.get("allow_force_pushes")
    allow_delete = protection.get("allow_deletions")
    bypass = reviews.get("bypass_pull_request_allowances") or {}
    bypassed = any(bypass.get(kind) for kind in ("users", "teams", "apps"))
    requires_pull_request = pr is not None or protection.get("required_pull_request_reviews") is not None
    required_reviews = int(
        params.get("required_approving_review_count", reviews.get("required_approving_review_count", 0))
    )
    if bypassed:
        requires_pull_request = False
        required_reviews = 0
    modeled = {
        "pull_request",
        "required_status_checks",
        "non_fast_forward",
        "deletion",
        "required_linear_history",
    }
    return {
        "requires_pull_request": requires_pull_request,
        "required_reviews": required_reviews,
        "dismiss_stale_reviews": bool(
            params.get("dismiss_stale_reviews_on_push", reviews.get("dismiss_stale_reviews", False))
        ),
        "require_thread_resolution": bool(
            params.get(
                "required_review_thread_resolution",
                (protection.get("required_conversation_resolution") or {}).get("enabled", False),
            )
        ),
        "block_force_push": any(rule.get("type") == "non_fast_forward" for rule in rules)
        or (isinstance(allow_force, dict) and allow_force.get("enabled") is not True),
        "block_deletion": any(rule.get("type") == "deletion" for rule in rules)
        or (isinstance(allow_delete, dict) and allow_delete.get("enabled") is not True),
        "enforce_admins": classic_admin or (any(rule.get("type") in modeled for rule in rules) and not protection),
        "required_status_checks": sorted(set(contexts)),
    }


def _environment(raw: dict[str, Any], policies: list[dict[str, Any]]) -> dict[str, Any]:
    rules = raw.get("protection_rules") or []
    reviewer_rule: dict[str, Any] = next((rule for rule in rules if rule.get("type") == "required_reviewers"), {})
    wait_rule: dict[str, Any] = next((rule for rule in rules if rule.get("type") == "wait_timer"), {})
    reviewers = []
    for entry in reviewer_rule.get("reviewers", raw.get("reviewers", ())) or ():
        reviewer = entry.get("reviewer") if isinstance(entry.get("reviewer"), dict) else entry
        kind = str(entry.get("type", reviewer.get("type", ""))).title()
        item = {"type": kind, "id": reviewer.get("id"), "node_id": reviewer.get("node_id")}
        item["login" if kind == "User" else "slug"] = reviewer.get("login" if kind == "User" else "slug")
        reviewers.append(item)
    return {
        "reviewers": reviewers,
        "minimum_approvals": 1,
        "prevent_self_review": bool(reviewer_rule.get("prevent_self_review", raw.get("prevent_self_review"))),
        "branch_patterns": sorted(str(item["name"]) for item in policies if item.get("type", "branch") == "branch"),
        "tag_patterns": sorted(str(item["name"]) for item in policies if item.get("type") == "tag"),
        "wait_timer": int(wait_rule.get("wait_timer", raw.get("wait_timer", 0)) or 0),
        "custom_rules": [rule for rule in rules if rule.get("type") not in {"required_reviewers", "wait_timer"}],
        "can_admins_bypass": raw.get("can_admins_bypass"),
    }


def collect_live_authority_snapshot(
    repository: str, expected: dict[str, Any], read: JsonReader = _gh
) -> dict[str, Any]:
    repo = read(f"repos/{repository}", False)
    branch = repo["default_branch"]
    rulesets = flatten_paginated_pages(
        read(f"repos/{repository}/rulesets?includes_parents=false&per_page=100", True), None
    )
    rulesets = [read(f"repos/{repository}/rulesets/{item['id']}", False) for item in rulesets]
    effective = read(f"repos/{repository}/rules/branches/{quote(branch, safe='')}", True)
    effective = flatten_paginated_pages(effective, None)
    protection = read(f"repos/{repository}/branches/{quote(branch, safe='')}/protection", False)
    environment_summaries = flatten_paginated_pages(
        read(f"repos/{repository}/environments?per_page=100", True), "environments"
    )
    environments = {}
    for name in sorted(item["name"] for item in environment_summaries):
        raw = read(f"repos/{repository}/environments/{quote(name, safe='')}", False)
        policies = flatten_paginated_pages(
            read(
                f"repos/{repository}/environments/{quote(name, safe='')}/deployment-branch-policies?per_page=100", True
            ),
            "branch_policies",
        )
        environments[name] = _environment(raw, policies)
    security_raw = repo.get("security_and_analysis") or {}
    security_map = {
        "secret_scanning": "secret_scanning",
        "secret_scanning_push_protection": "secret_push_protection",
        "dependabot_security_updates": "dependency_scanning",
    }
    security = {
        output: value.get("status") == "enabled"
        for source, output in security_map.items()
        if isinstance((value := security_raw.get(source)), dict)
    }
    checks: list[dict[str, Any]] = []
    classic_checks = protection.get("required_status_checks") or {}
    detailed_contexts = set()
    for item in classic_checks.get("checks") or ():
        detailed_contexts.add(item["context"])
        checks.append(
            {"context": item["context"], "app_id": item.get("app_id"), "integration_id": None, "source": "classic"}
        )
    checks += [
        {"context": context, "app_id": None, "integration_id": None, "source": "classic"}
        for context in classic_checks.get("contexts") or ()
        if context not in detailed_contexts
    ]
    for ruleset in rulesets:
        for rule in ruleset.get("rules") or ():
            if rule.get("type") == "required_status_checks":
                checks += [
                    {
                        "context": item["context"],
                        "app_id": None,
                        "integration_id": item.get("integration_id"),
                        "source": f"ruleset:{ruleset['id']}",
                    }
                    for item in (rule.get("parameters") or {}).get("required_status_checks") or ()
                ]
    guard = expected.get("guard") or {}
    for descriptor in guard.values():
        current = (
            read(
                f"repos/{descriptor['repository']}/contents/{descriptor['path']}"
                f"?ref={quote(descriptor['ref'], safe='')}",
                False,
            )
            if "repository" in descriptor
            else read(f"repos/{repository}/contents/{descriptor['path']}?ref={quote(branch, safe='')}", False)
        )
        if current.get("sha") != descriptor.get("blob_sha"):
            raise ValueError("authority snapshot guard blob drifted")
    checks.sort(key=lambda item: (item["context"], str(item["app_id"]), str(item["integration_id"]), item["source"]))
    repository_identity = {
        "database_id": repo["id"],
        "node_id": repo["node_id"],
        "full_name": repo["full_name"],
        "default_branch": branch,
    }
    live_state = {
        "classic": _classic(effective, protection),
        "repository": {},
        "security": security,
        "merge": {
            key: bool(repo[key])
            for key in ("allow_merge_commit", "allow_squash_merge", "allow_rebase_merge")
            if key in repo
        },
        "rulesets": sorted(rulesets, key=lambda item: item["id"]),
        "environments": environments,
        "required_checks": checks,
        "guard": guard.get("intake"),
        "release_guard": guard.get("release"),
        "verifier_guard": guard.get("verifier"),
    }
    return project_authority_snapshot(repository_identity, live_state)


def require_exact_authority_snapshot(expected: dict[str, Any], current: dict[str, Any]) -> None:
    if expected.get("schema") != AUTHORITY_SNAPSHOT_SCHEMA or expected != current:
        raise ValueError("current authority snapshot differs from signed checkpoint authority snapshot")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envelope", required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args(argv)
    raw = pathlib.Path(args.envelope).read_bytes()
    envelope = json.loads(raw)
    if raw != json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii"):
        raise SystemExit("checkpoint envelope is not canonical")
    checkpoint = envelope["checkpoint"]
    now = int(time.time())
    if checkpoint["issued_at"] > now + 30 or checkpoint["expires_at"] <= now:
        raise SystemExit("checkpoint is outside bounded freshness")
    reviewer = checkpoint["reviewer"]
    permission = _gh(f"repos/{args.repository}/collaborators/{reviewer}/permission")
    selected = select_unique_signing_key(
        _gh(f"users/{reviewer}/ssh_signing_keys?per_page=100", True), str(envelope["key_id"])
    )
    if permission.get("permission") != "admin":
        raise SystemExit("reviewer admin/key authority is not current")
    signature = base64.urlsafe_b64decode(envelope["signature"] + "=" * (-len(envelope["signature"]) % 4))
    try:
        verify_ssh_signature(
            json.dumps(checkpoint, sort_keys=True, separators=(",", ":")).encode("ascii"),
            signature,
            reviewer,
            selected["key"],
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    expected = checkpoint["authority_snapshot"]
    require_exact_authority_snapshot(expected, collect_live_authority_snapshot(args.repository, expected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
