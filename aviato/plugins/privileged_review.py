"""Hardened live collector for privileged-review activation evidence.

This module is intentionally read-only.  It uses a dedicated token and a
fixed TLS origin, never the ambient gh credential, proxy environment, or an
HTTP redirect.  Candidate code supplies identifiers only; every authoritative
value is reconstructed from GitHub and compared to the signed envelope.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import secrets
import ssl
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..command import DEFAULT_TIMEOUT_SECONDS

_API_HOST = "api.github.com"
_TOKEN_ENV = "AVIATO_PRIVILEGED_REVIEW_TOKEN"
_POLICY_PATH = "aviato/library/privileged-review-policy.json"
_CODEOWNERS_PATH = ".github/CODEOWNERS"
_TRUSTED_WORKFLOW_PATH = ".github/workflows/aviato-privileged-review.yml"
_MAX_ENVELOPE_BASE64_CHARS = 60_000
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}")
_DANGEROUS_NETWORK_ENV = {
    "ALL_PROXY",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "all_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
}
_REQUIRED_APP_PERMISSIONS = {
    "actions": "read",
    "administration": "read",
    "contents": "read",
    "members": "read",
    "metadata": "read",
    "pull_requests": "read",
}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _assert_clean_network_environment() -> None:
    present = sorted(name for name in _DANGEROUS_NETWORK_ENV if os.environ.get(name))
    if present:
        raise ValueError(f"privileged review network environment contains proxy/TLS overrides: {present!r}")


def _repository_slug(value: object) -> str:
    if not isinstance(value, str) or _REPOSITORY_RE.fullmatch(value) is None:
        raise ValueError("repository slug is not one strict OWNER/REPO identity")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."} or name.endswith(".git"):
        raise ValueError("repository slug contains a forbidden path-like segment")
    return value


def _sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"{label} is not one immutable Git SHA")
    return value


def _identifier(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} is not one positive integer identity")
    return value


def _request_json(path: str, *, token: str, payload: dict[str, Any] | None = None) -> Any:
    """Read one exact api.github.com resource without proxy or redirect support."""

    _assert_clean_network_environment()
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or "\r" in path
        or "\n" in path
        or "http:" in path.lower()
        or "https:" in path.lower()
    ):
        raise ValueError("GitHub API request path is not an exact-origin relative path")
    body = None if payload is None else _canonical(payload).encode("ascii")
    method = "GET" if payload is None else "POST"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "aviato-privileged-review/1",
        "X-GitHub-Api-Version": "2022-11-28",
        "Cache-Control": "no-cache",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    # HTTPSConnection talks directly to this literal origin. It does not read
    # *_PROXY/NO_PROXY and does not implement redirect following.
    connection = http.client.HTTPSConnection(
        _API_HOST,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
    finally:
        connection.close()
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("GitHub API response exceeds the bounded collector limit")
    if response.status in {301, 302, 303, 307, 308}:
        raise ValueError("GitHub API redirect refused")
    if response.status < 200 or response.status >= 300:
        raise ValueError(f"GitHub API read failed with HTTP {response.status}")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("GitHub API response is not JSON") from exc
    return document


def _rest(path: str, *, token: str) -> Any:
    return _request_json(path, token=token)


def _graphql(query: str, variables: dict[str, Any], *, token: str) -> dict[str, Any]:
    document = _request_json("/graphql", token=token, payload={"query": query, "variables": variables})
    data = document.get("data") if isinstance(document, dict) else None
    if not isinstance(document, dict) or document.get("errors") or not isinstance(data, dict):
        raise ValueError("GitHub GraphQL read is unavailable or ambiguous")
    return data


def _decode_content(document: object, *, label: str) -> tuple[bytes, str]:
    if not isinstance(document, dict) or document.get("encoding") != "base64":
        raise ValueError(f"{label} content response is invalid")
    encoded = document.get("content")
    blob_sha = document.get("sha")
    if not isinstance(encoded, str) or not isinstance(blob_sha, str) or re.fullmatch(r"[0-9a-f]{40}", blob_sha) is None:
        raise ValueError(f"{label} content identity is invalid")
    try:
        body = base64.b64decode("".join(encoded.split()), validate=True)
    except ValueError as exc:
        raise ValueError(f"{label} content is not canonical base64") from exc
    if not body:
        raise ValueError(f"{label} content is empty")
    return body, blob_sha


def _load_json_content(document: object, *, label: str) -> tuple[dict[str, Any], str]:
    body, blob_sha = _decode_content(document, label=label)
    try:
        loaded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} content is not JSON") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{label} content is not a mapping")
    return loaded, blob_sha


def _covered(path: str, protected: list[str]) -> bool:
    logical = "/" + path
    return any(logical == item or (item.endswith("/") and logical.startswith(item)) for item in protected)


def _tree_inventory(repository: str, sha: str, protected: list[str], *, token: str) -> list[dict[str, str]]:
    repository = _repository_slug(repository)
    sha = _sha(sha, label="tree SHA")
    document = _rest(f"/repos/{repository}/git/trees/{sha}?recursive=1", token=token)
    if (
        not isinstance(document, dict)
        or document.get("truncated") is not False
        or not isinstance(document.get("tree"), list)
    ):
        raise ValueError("protected Git tree read is missing, truncated, or ambiguous")
    selected: list[dict[str, str]] = []
    for item in document["tree"]:
        if not isinstance(item, dict) or item.get("type") != "blob" or not isinstance(item.get("path"), str):
            continue
        path = item["path"]
        if not _covered(path, protected):
            continue
        mode = item.get("mode")
        blob_sha = item.get("sha")
        if mode not in {"100644", "100755"} or not isinstance(blob_sha, str):
            raise ValueError(f"protected path is not one regular reviewed file: /{path}")
        blob = _rest(f"/repos/{repository}/git/blobs/{blob_sha}", token=token)
        body, returned_sha = _decode_content(blob, label=f"protected blob /{path}")
        if returned_sha != blob_sha:
            raise ValueError(f"protected blob identity changed during collection: /{path}")
        selected.append({"path": f"/{path}", "mode": mode, "sha256": hashlib.sha256(body).hexdigest()})
    selected.sort(key=lambda item: item["path"])
    for protected_path in protected:
        if not any(
            item["path"] == protected_path or (protected_path.endswith("/") and item["path"].startswith(protected_path))
            for item in selected
        ):
            raise ValueError(f"trusted protected path has no reviewed file: {protected_path}")
    return selected


def _codeowner_tokens(body: bytes, path: str) -> set[str]:
    """Resolve the repository's deliberately simple exact/prefix CODEOWNERS routes."""

    try:
        lines = body.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("trusted base CODEOWNERS is not UTF-8") from exc
    matched: set[str] = set()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 2:
            raise ValueError("trusted base CODEOWNERS contains an invalid route")
        pattern = fields[0]
        # Privileged routes are intentionally restricted to exact absolute paths
        # or absolute directory prefixes; wildcard semantics would be ambiguous.
        if any(character in pattern for character in "*?[]!\\") or not pattern.startswith("/"):
            raise ValueError("trusted privileged CODEOWNERS uses an unsupported ambiguous pattern")
        if path == pattern or (pattern.endswith("/") and path.startswith(pattern)):
            matched = {owner for owner in fields[1:] if owner.startswith("@")}
    if not matched:
        raise ValueError(f"trusted base CODEOWNERS has no owner for {path}")
    return matched


_PR_QUERY = """
query AviatoPrivilegedReview($owner:String!,$name:String!,$number:Int!) {
  repository(owner:$owner,name:$name) {
    pullRequest(number:$number) {
      headRefOid
      commits(last:1) { nodes { commit { oid pushedDate } } }
      reviews(first:100) {
        pageInfo { hasNextPage }
        nodes {
          databaseId id state submittedAt lastEditedAt dismissedAt
          commit { oid }
          author { login ... on User { databaseId } }
        }
      }
    }
  }
}
"""


def _pull_graph(repository: str, number: int, *, token: str) -> dict[str, Any]:
    repository = _repository_slug(repository)
    number = _identifier(number, label="pull request number")
    owner, name = repository.split("/", 1)
    data = _graphql(_PR_QUERY, {"owner": owner, "name": name, "number": number}, token=token)
    repo = data.get("repository")
    pull = repo.get("pullRequest") if isinstance(repo, dict) else None
    reviews = pull.get("reviews") if isinstance(pull, dict) else None
    if (
        not isinstance(pull, dict)
        or not isinstance(reviews, dict)
        or reviews.get("pageInfo", {}).get("hasNextPage") is not False
        or not isinstance(reviews.get("nodes"), list)
    ):
        raise ValueError("pull request review graph is absent, paginated, or ambiguous")
    return pull


def _ruleset(repository: str, ruleset_id: int, *, token: str) -> dict[str, Any]:
    repository = _repository_slug(repository)
    ruleset_id = _identifier(ruleset_id, label="ruleset id")
    payload = _rest(f"/repos/{repository}/rulesets/{ruleset_id}", token=token)
    if not isinstance(payload, dict):
        raise ValueError("live ruleset is unavailable")
    return payload


def _environment_authority(repository: str, name: str, *, token: str) -> dict[str, Any]:
    repository = _repository_slug(repository)
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name) is None:
        raise ValueError("trusted review environment name is invalid")
    payload = _rest(f"/repos/{repository}/environments/{quote(name, safe='')}", token=token)
    rules = payload.get("protection_rules") if isinstance(payload, dict) else None
    reviewer_rules = (
        [rule for rule in rules if isinstance(rule, dict) and rule.get("type") == "required_reviewers"]
        if isinstance(rules, list)
        else []
    )
    if len(reviewer_rules) != 1 or not isinstance(reviewer_rules[0].get("reviewers"), list):
        raise ValueError("trusted review environment has no unambiguous external-reviewer rule")
    reviewers: list[dict[str, Any]] = []
    for item in reviewer_rules[0]["reviewers"]:
        reviewer = item.get("reviewer") if isinstance(item, dict) else None
        kind = item.get("type") if isinstance(item, dict) else None
        login_key = "login" if kind == "User" else "slug" if kind == "Team" else ""
        if (
            not isinstance(reviewer, dict)
            or type(reviewer.get("id")) is not int
            or not isinstance(reviewer.get("node_id"), str)
            or not login_key
            or not isinstance(reviewer.get(login_key), str)
        ):
            raise ValueError("trusted review environment reviewer identity is incomplete")
        reviewers.append(
            {
                "type": kind,
                "database_id": reviewer["id"],
                "node_id": reviewer["node_id"],
                "login": reviewer[login_key],
            }
        )
    reviewers.sort(key=lambda item: (str(item["type"]), int(item["database_id"])))
    branch_policy = payload.get("deployment_branch_policy") if isinstance(payload, dict) else None
    normalized = {
        "name": payload.get("name") if isinstance(payload, dict) else None,
        "can_admins_bypass": payload.get("can_admins_bypass") if isinstance(payload, dict) else None,
        "prevent_self_review": reviewer_rules[0].get("prevent_self_review"),
        "reviewers": reviewers,
        "deployment_branch_policy": branch_policy,
    }
    normalized["payload_sha256"] = _digest(normalized)
    return normalized


def _installation_authority(repository_id: int, *, token: str) -> dict[str, Any]:
    installation = _rest("/installation", token=token)
    if not isinstance(installation, dict):
        raise ValueError("credential is not one GitHub App installation token")
    permissions = installation.get("permissions")
    app_slug = installation.get("app_slug")
    if (
        type(installation.get("id")) is not int
        or type(installation.get("app_id")) is not int
        or not isinstance(app_slug, str)
        or not app_slug
        or installation.get("suspended_at") is not None
        or not isinstance(permissions, dict)
    ):
        raise ValueError("GitHub App installation identity is incomplete or suspended")
    if permissions != _REQUIRED_APP_PERMISSIONS:
        raise ValueError("GitHub App installation permissions are missing reads or include excess/write authority")
    repositories: list[dict[str, Any]] = []
    total_count: int | None = None
    for page in range(1, 1001):
        document = _rest(f"/installation/repositories?per_page=100&page={page}", token=token)
        if (
            not isinstance(document, dict)
            or type(document.get("total_count")) is not int
            or not isinstance(document.get("repositories"), list)
        ):
            raise ValueError("GitHub App installation repository selection is unavailable")
        if total_count is None:
            total_count = document["total_count"]
        elif total_count != document["total_count"]:
            raise ValueError("GitHub App installation repository selection changed while paginating")
        page_items = document["repositories"]
        if any(not isinstance(item, dict) or type(item.get("id")) is not int for item in page_items):
            raise ValueError("GitHub App installation repository identity is invalid")
        repositories.extend(page_items)
        if len(page_items) < 100:
            break
    if total_count is None or len(repositories) != total_count:
        raise ValueError("GitHub App installation repository pagination is incomplete or ambiguous")
    selected = [item for item in repositories if item.get("id") == repository_id]
    if len(selected) != 1:
        raise ValueError("GitHub App installation token does not select exactly this repository")
    return {
        "app_id": installation["app_id"],
        "installation_id": installation["id"],
        "app_slug": app_slug,
        "permissions": permissions,
        "repository_ids": sorted(item["id"] for item in repositories),
        "suspended_at": None,
    }


def collect_live_privileged_review_evidence(
    envelope: dict[str, Any],
    *,
    allow_in_progress_unsigned_collection: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Reconstruct every signed authority field from current GitHub reads."""

    _assert_clean_network_environment()
    token = os.environ.get(_TOKEN_ENV)
    if not token or any(character.isspace() for character in token):
        raise ValueError(f"{_TOKEN_ENV} must contain one dedicated read-only GitHub App token")
    evidence = envelope.get("evidence") if isinstance(envelope, dict) else None
    if not isinstance(evidence, dict):
        raise ValueError("signed review evidence is missing")
    recorded_repo = evidence.get("repository")
    recorded_pr = evidence.get("pull_request")
    recorded_ruleset = evidence.get("ruleset")
    if (
        not isinstance(recorded_repo, dict)
        or not isinstance(recorded_pr, dict)
        or not isinstance(recorded_ruleset, dict)
    ):
        raise ValueError("signed review evidence omitted live lookup identities")
    repository = _repository_slug(recorded_repo.get("full_name"))
    number = _identifier(recorded_pr.get("number"), label="pull request number")
    ruleset_payload = recorded_ruleset.get("payload")
    ruleset_id = _identifier(
        ruleset_payload.get("id") if isinstance(ruleset_payload, dict) else None, label="ruleset id"
    )

    repo = _rest(f"/repos/{repository}", token=token)
    pull = _rest(f"/repos/{repository}/pulls/{number}", token=token)
    graph = _pull_graph(repository, number, token=token)
    if not isinstance(repo, dict) or not isinstance(pull, dict):
        raise ValueError("repository or pull request is unavailable")
    base = pull.get("base")
    head = pull.get("head")
    user = pull.get("user")
    if not isinstance(base, dict) or not isinstance(head, dict) or not isinstance(user, dict):
        raise ValueError("pull request identity is incomplete")
    base_sha = base.get("sha")
    head_sha = head.get("sha")
    merged_sha = pull.get("merge_commit_sha")
    default_branch = repo.get("default_branch")
    if not isinstance(default_branch, str) or re.fullmatch(r"[A-Za-z0-9._/-]+", default_branch) is None:
        raise ValueError("default branch identity is invalid")
    base_sha = _sha(base_sha, label="pull request base SHA")
    head_sha = _sha(head_sha, label="pull request head SHA")
    merged_sha = _sha(merged_sha, label="pull request merged SHA")
    if not pull.get("merged"):
        raise ValueError("privileged review must be collected after the exact reviewed tree is merged")

    policy_doc = _rest(f"/repos/{repository}/contents/{_POLICY_PATH}?ref={quote(str(base_sha), safe='')}", token=token)
    trusted_policy, policy_blob_sha = _load_json_content(policy_doc, label="trusted base review policy")
    protected = trusted_policy.get("protected_paths")
    if not isinstance(protected, list) or any(not isinstance(path, str) for path in protected):
        raise ValueError("trusted base review policy protected paths are invalid")
    codeowners_doc = _rest(
        f"/repos/{repository}/contents/{_CODEOWNERS_PATH}?ref={quote(str(base_sha), safe='')}", token=token
    )
    codeowners_body, _codeowners_blob = _decode_content(codeowners_doc, label="trusted base CODEOWNERS")
    branch_path = f"/repos/{repository}/branches/{quote(default_branch, safe='')}"
    current_branch = _rest(branch_path, token=token)
    current_commit = current_branch.get("commit") if isinstance(current_branch, dict) else None
    current_default_branch_sha = _sha(
        current_commit.get("sha") if isinstance(current_commit, dict) else None,
        label="current default-branch SHA",
    )
    current_policy_doc = _rest(
        f"/repos/{repository}/contents/{_POLICY_PATH}?ref={quote(current_default_branch_sha, safe='')}",
        token=token,
    )
    current_policy, current_policy_blob_sha = _load_json_content(
        current_policy_doc, label="current default-branch review policy"
    )
    head_files = _tree_inventory(repository, str(head_sha), protected, token=token)
    merged_files = _tree_inventory(repository, str(merged_sha), protected, token=token)
    if merged_files != head_files:
        raise ValueError("merged protected-tree root differs from the reviewed head tree")
    base_files = _tree_inventory(repository, str(base_sha), protected, token=token)
    before = {item["path"]: (item["mode"], item["sha256"]) for item in base_files}
    after = {item["path"]: (item["mode"], item["sha256"]) for item in head_files}
    changed_paths = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))

    commits = graph.get("commits")
    commit_nodes = commits.get("nodes") if isinstance(commits, dict) else None
    commit = commit_nodes[0].get("commit") if isinstance(commit_nodes, list) and len(commit_nodes) == 1 else None
    if not isinstance(commit, dict):
        raise ValueError("latest pushed commit/time is unavailable or ambiguous")
    pushed_at = commit.get("pushedDate")
    if not isinstance(pushed_at, str) or commit.get("oid") != head_sha or graph.get("headRefOid") != head_sha:
        raise ValueError("latest pushed commit/time is unavailable or ambiguous")

    reviews_doc = graph.get("reviews")
    nodes = reviews_doc.get("nodes") if isinstance(reviews_doc, dict) else None
    if not isinstance(nodes, list):
        raise ValueError("current review collection is unavailable")
    # GitHub retains historical review nodes. Only each reviewer's latest
    # opinion is current authority; a later CHANGES_REQUESTED/DISMISSED node
    # must invalidate an older approval.
    latest: dict[int, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict) or node.get("state") not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            # COMMENTED/PENDING nodes are not review opinions. GitHub Apps and
            # deleted users may also leave non-opinionated historical nodes;
            # neither can invalidate a concrete user's current approval.
            continue
        author = node.get("author")
        reviewer_id = author.get("databaseId") if isinstance(author, dict) else None
        if type(reviewer_id) is not int:
            # Bot opinions are never eligible authority and do not share a user
            # database identity with the concrete reviewers selected below.
            continue
        if not isinstance(node.get("submittedAt"), str):
            raise ValueError("current opinionated review has no immutable submission time")
        prior = latest.get(reviewer_id)
        if prior is None or (node["submittedAt"], int(node.get("databaseId") or 0)) > (
            str(prior.get("submittedAt")),
            int(prior.get("databaseId") or 0),
        ):
            latest[reviewer_id] = node
    approvals: list[dict[str, Any]] = []
    for node in latest.values():
        if node.get("state") != "APPROVED":
            continue
        author = node.get("author")
        review_commit = node.get("commit")
        if not isinstance(author, dict) or not isinstance(review_commit, dict):
            raise ValueError("current approval identity is incomplete")
        reviewer_id = author.get("databaseId")
        login = author.get("login")
        if type(reviewer_id) is not int or not isinstance(login, str):
            raise ValueError("current approval reviewer is not one concrete user")
        team_id: int | None = None
        team_membership: bool | None = None
        eligible_paths: list[str] = []
        for changed in changed_paths:
            owners = _codeowner_tokens(codeowners_body, changed)
            direct = f"@{login}".casefold() in {owner.casefold() for owner in owners}
            teams = [owner[1:] for owner in owners if "/" in owner]
            member_team_ids: list[int] = []
            for team in teams:
                organization, slug = team.split("/", 1)
                team_doc = _rest(f"/orgs/{organization}/teams/{slug}", token=token)
                membership = _rest(f"/orgs/{organization}/teams/{slug}/memberships/{login}", token=token)
                if not isinstance(team_doc, dict) or type(team_doc.get("id")) is not int:
                    raise ValueError("CODEOWNER team identity is unavailable")
                if isinstance(membership, dict) and membership.get("state") == "active":
                    member_team_ids.append(team_doc["id"])
            if direct or len(member_team_ids) == 1:
                eligible_paths.append(changed)
            if len(member_team_ids) > 1:
                raise ValueError("reviewer team eligibility is ambiguous")
            if member_team_ids:
                if team_id not in {None, member_team_ids[0]}:
                    raise ValueError("one review resolves to different CODEOWNER teams")
                team_id = member_team_ids[0]
                team_membership = True
        approvals.append(
            {
                "review_id": node.get("databaseId"),
                "node_id": node.get("id"),
                "reviewer_database_id": reviewer_id,
                "reviewer_login": login,
                "state": node.get("state"),
                "commit_sha": review_commit.get("oid"),
                "submitted_at": node.get("submittedAt"),
                "dismissed": node.get("dismissedAt") is not None,
                "edited": node.get("lastEditedAt") is not None,
                "is_author": reviewer_id == user.get("id"),
                "eligible_codeowner_paths": sorted(eligible_paths),
                "team_database_id": team_id,
                "team_membership": team_membership,
            }
        )
    approvals.sort(key=lambda item: (str(item["submitted_at"]), int(item["review_id"] or 0)))

    workflow = evidence.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("trusted workflow run identity is missing")
    run_id = _identifier(workflow.get("run_id"), label="workflow run id")
    run = _rest(f"/repos/{repository}/actions/runs/{run_id}", token=token)
    repository_id = _identifier(repo.get("id"), label="repository id")
    collector = _installation_authority(repository_id, token=token)
    trusted_workflow_path = trusted_policy.get("trusted_workflow_path")
    run_repository = run.get("repository") if isinstance(run, dict) else None
    actor = run.get("actor") if isinstance(run, dict) else None
    triggering_actor = run.get("triggering_actor") if isinstance(run, dict) else None
    terminal = isinstance(run, dict) and run.get("status") == "completed" and run.get("conclusion") == "success"
    collecting = (
        allow_in_progress_unsigned_collection
        and isinstance(run, dict)
        and run.get("status") == "in_progress"
        and run.get("conclusion") is None
    )
    if (
        not isinstance(run, dict)
        or trusted_workflow_path != _TRUSTED_WORKFLOW_PATH
        or run.get("path") != trusted_workflow_path
        or run.get("head_branch") != default_branch
        or run.get("head_sha") != merged_sha
        or run.get("event") != "workflow_dispatch"
        or run.get("id") != run_id
        or not isinstance(run_repository, dict)
        or run_repository.get("id") != repository_id
        or not isinstance(actor, dict)
        or type(actor.get("id")) is not int
        or not isinstance(actor.get("login"), str)
        or not isinstance(triggering_actor, dict)
        or type(triggering_actor.get("id")) is not int
        or not isinstance(triggering_actor.get("login"), str)
        or type(run.get("workflow_id")) is not int
        or type(run.get("run_attempt")) is not int
        or run.get("run_attempt", 0) <= 0
        or not (terminal or collecting)
    ):
        raise ValueError("trusted default-branch collector workflow is not one successful immutable run")
    workflow_doc = _rest(
        f"/repos/{repository}/contents/{trusted_workflow_path}?ref={quote(str(merged_sha), safe='')}", token=token
    )
    workflow_body, workflow_blob_sha = _decode_content(workflow_doc, label="trusted collector workflow")
    trusted_environment = trusted_policy.get("trusted_environment")
    current_environment = current_policy.get("trusted_environment")
    if trusted_environment != current_environment or not isinstance(trusted_environment, str):
        raise ValueError("base/current trusted review environment identity differs")
    environment = _environment_authority(repository, trusted_environment, token=token)

    live = dict(evidence)
    live.update(
        {
            "repository": {
                "database_id": repo.get("id"),
                "node_id": repo.get("node_id"),
                "full_name": repo.get("full_name"),
                "default_branch": default_branch,
            },
            "pull_request": {
                "number": pull.get("number"),
                "author_database_id": user.get("id"),
                "author_login": user.get("login"),
                "base_sha": base_sha,
                "head_sha": head_sha,
                "last_push_sha": graph.get("headRefOid"),
                "last_push_at": pushed_at,
                "merged_sha": merged_sha,
                "protected_tree_root": _digest(head_files),
            },
            "protected_files": head_files,
            "changed_protected_paths": changed_paths,
            "reviews": approvals,
            "ruleset": {
                "payload": _ruleset(repository, ruleset_id, token=token),
                "payload_sha256": "",
            },
            "collector": collector,
            "workflow": {
                "repository_id": repo.get("id"),
                "path": trusted_workflow_path,
                "ref": f"refs/heads/{default_branch}",
                "blob_sha": workflow_blob_sha,
                "blob_sha256": hashlib.sha256(workflow_body).hexdigest(),
                "run_head_sha": run.get("head_sha"),
                "run_id": run.get("id"),
                "workflow_database_id": run.get("workflow_id"),
                "run_attempt": run.get("run_attempt"),
                "event": run.get("event"),
                # Unsigned collection occurs while its own run is in progress.
                # The offline signer acts only after it completes; every later
                # verifier requires these exact successful terminal values.
                "status": "completed",
                "conclusion": "success",
                "actor_database_id": actor.get("id"),
                "actor_login": actor.get("login"),
                "triggering_actor_database_id": triggering_actor.get("id"),
                "triggering_actor_login": triggering_actor.get("login"),
                "environment": trusted_environment,
            },
            "environment": environment,
            "trust_root": {
                "base_sha": base_sha,
                "policy_blob_sha": policy_blob_sha,
                "policy_sha256": _digest(trusted_policy),
            },
        }
    )
    live["ruleset"]["payload_sha256"] = _digest(live["ruleset"]["payload"])
    current_branch_after = _rest(branch_path, token=token)
    current_commit_after = current_branch_after.get("commit") if isinstance(current_branch_after, dict) else None
    if not isinstance(current_commit_after, dict) or current_commit_after.get("sha") != current_default_branch_sha:
        raise ValueError("current default-branch policy ref moved during live collection")
    # The current policy is deliberately returned as a separate runtime trust
    # input. Binding its ref/blob into the signed snapshot would invalidate a
    # supported release after every unrelated default-branch advance.
    del current_policy_blob_sha
    return trusted_policy, current_policy, live


def collect_unsigned_evidence(
    *,
    repository: str,
    pull_request: int,
    ruleset_id: int,
    workflow_run_id: int,
    key_id: str,
    key_version: int,
    now: int | None = None,
) -> dict[str, Any]:
    """Collect canonical unsigned evidence from the protected workflow run."""

    repository = _repository_slug(repository)
    pull_request = _identifier(pull_request, label="pull request number")
    ruleset_id = _identifier(ruleset_id, label="ruleset id")
    workflow_run_id = _identifier(workflow_run_id, label="workflow run id")
    key_version = _identifier(key_version, label="signing key version")
    if not isinstance(key_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", key_id) is None:
        raise ValueError("signing key id is invalid")
    issued_at = int(time.time()) if now is None else now
    if issued_at <= 0:
        raise ValueError("collection time is invalid")
    seed = {
        "schema": "aviato-privileged-review-evidence/v1",
        "status": "approved",
        "lifecycle": "consumed",
        "repository": {"full_name": repository},
        "pull_request": {"number": pull_request},
        "ruleset": {"payload": {"id": ruleset_id}},
        "workflow": {"path": _TRUSTED_WORKFLOW_PATH, "run_id": workflow_run_id},
        "issuer": "aviato-privileged-review",
        "issued_at": issued_at,
        "expires_at": issued_at + 1,
        "key_id": key_id,
        "key_version": key_version,
        "nonce": secrets.token_hex(32),
    }
    trusted_policy, current_policy, evidence = collect_live_privileged_review_evidence(
        {"evidence": seed}, allow_in_progress_unsigned_collection=True
    )
    base_ttl = trusted_policy.get("maximum_attestation_ttl_seconds")
    current_ttl = current_policy.get("maximum_attestation_ttl_seconds")
    ttl = min(base_ttl, current_ttl) if type(base_ttl) is int and type(current_ttl) is int else 0
    if type(ttl) is not int or not 31_536_000 <= ttl <= 63_072_000:
        raise ValueError("trusted review evidence TTL is invalid")
    keys = trusted_policy.get("trusted_signing_keys")
    current_keys = current_policy.get("trusted_signing_keys")
    if not isinstance(keys, list) or not isinstance(current_keys, list):
        raise ValueError("trusted review signing-key lifecycle is invalid")

    def matching(records: list[object]) -> list[dict[str, Any]]:
        return [
            item
            for item in records
            if isinstance(item, dict)
            and item.get("key_id") == key_id
            and item.get("key_version") == key_version
            and item.get("issuer") == seed["issuer"]
        ]

    base_matching = matching(keys)
    current_matching = matching(current_keys)
    if (
        len(base_matching) != 1
        or len(current_matching) != 1
        or base_matching[0].get("public_key") != current_matching[0].get("public_key")
    ):
        raise ValueError("requested offline signing key is not active in the immutable base policy")
    evidence["expires_at"] = issued_at + ttl
    return evidence


def sign_collected_evidence(evidence_path: Path, private_key_path: Path, output_path: Path) -> None:
    """Sign collected bytes offline; the private key never enters GitHub Actions."""

    try:
        evidence_metadata = evidence_path.lstat()
        key_metadata = private_key_path.lstat()
    except OSError as exc:
        raise ValueError("collected evidence/private key is unavailable") from exc
    if not stat.S_ISREG(evidence_metadata.st_mode) or not stat.S_ISREG(key_metadata.st_mode):
        raise ValueError("collected evidence and offline private key must be regular non-symlink files")
    if output_path.exists() or output_path.is_symlink():
        raise ValueError("offline signed-envelope output already exists")
    raw = evidence_path.read_bytes()
    try:
        evidence = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("collected evidence is not canonical JSON") from exc
    if (
        not isinstance(evidence, dict)
        or raw != _canonical(evidence).encode("ascii")
        or evidence.get("schema") != "aviato-privileged-review-evidence/v1"
        or evidence.get("status") != "approved"
        or evidence.get("lifecycle") != "consumed"
        or evidence.get("issuer") != "aviato-privileged-review"
        or not isinstance(evidence.get("key_id"), str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", evidence["key_id"]) is None
        or type(evidence.get("key_version")) is not int
        or evidence["key_version"] <= 0
        or not isinstance(evidence.get("nonce"), str)
        or re.fullmatch(r"[0-9a-f]{64}", evidence["nonce"]) is None
    ):
        raise ValueError("collected evidence is not one canonical consumed review snapshot")
    signature_path = Path(str(evidence_path) + ".sig")
    if signature_path.exists() or signature_path.is_symlink():
        raise ValueError("offline SSH signature output already exists")
    try:
        result = subprocess.run(
            [
                "/usr/bin/ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(private_key_path),
                "-n",
                "aviato-privileged-review",
                str(evidence_path),
            ],
            capture_output=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            check=False,
        )
        signature_metadata = signature_path.lstat() if signature_path.exists() else None
        if result.returncode != 0 or signature_metadata is None or not stat.S_ISREG(signature_metadata.st_mode):
            raise ValueError("offline SSH evidence signing failed")
        signature = signature_path.read_bytes()
    finally:
        signature_path.unlink(missing_ok=True)
    envelope = {
        "schema": "aviato-privileged-review-envelope/v1",
        "algorithm": "ssh-ed25519",
        "evidence": evidence,
        "signature": base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
    }
    _write_private_output(output_path, _canonical(envelope).encode("ascii"))


def verify_signed_envelope(envelope: dict[str, Any]) -> list[str]:
    """Freshly re-collect and verify an externally signed package input."""

    from .release_mutations import verify_privileged_review_envelope

    trusted_policy, current_policy, live = collect_live_privileged_review_evidence(envelope)
    return verify_privileged_review_envelope(
        envelope,
        trusted_base_policy=trusted_policy,
        current_policy=current_policy,
        live_evidence=live,
        now=int(time.time()),
        verify_signature=verify_ssh_review_signature,
    )


def verify_ssh_review_signature(public_key: bytes, message: bytes, signature: bytes, principal: str) -> bool:
    """Verify exact evidence bytes with an absolute binary and minimal environment."""

    try:
        key_text = public_key.decode("ascii")
    except UnicodeDecodeError:
        return False
    if (
        not message
        or not signature
        or not principal
        or "\n" in principal
        or re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/]+={0,2}", key_text) is None
    ):
        return False
    with tempfile.TemporaryDirectory(prefix="aviato-privileged-review-") as directory:
        root = Path(directory)
        allowed = root / "allowed_signers"
        signed = root / "signature"
        allowed.write_bytes(principal.encode("ascii") + b" " + public_key.rstrip(b"\n") + b"\n")
        signed.write_bytes(signature)
        try:
            result = subprocess.run(
                [
                    "/usr/bin/ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed),
                    "-I",
                    principal,
                    "-n",
                    "aviato-privileged-review",
                    "-s",
                    str(signed),
                ],
                input=message,
                capture_output=True,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0


def _positive_argument(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be one positive integer") from exc
    if parsed <= 0 or str(parsed) != value:
        raise argparse.ArgumentTypeError("value must be one canonical positive integer")
    return parsed


def _write_private_output(path: Path, body: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(body)


def main(argv: list[str] | None = None) -> int:
    """Protected collect, offline sign, and fresh verify lifecycle."""

    parser = argparse.ArgumentParser(prog="python -m aviato.plugins.privileged_review")
    subparsers = parser.add_subparsers(dest="phase", required=True)
    collect = subparsers.add_parser("collect")
    collect.add_argument("--repository", required=True)
    collect.add_argument("--pull-request", required=True, type=_positive_argument)
    collect.add_argument("--ruleset-id", required=True, type=_positive_argument)
    collect.add_argument("--workflow-run-id", required=True, type=_positive_argument)
    collect.add_argument("--key-id", required=True)
    collect.add_argument("--key-version", required=True, type=_positive_argument)
    collect.add_argument("--output", required=True, type=Path)

    sign = subparsers.add_parser("sign")
    sign.add_argument("--evidence", required=True, type=Path)
    sign.add_argument("--private-key", required=True, type=Path)
    sign.add_argument("--output", required=True, type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.phase == "collect":
            evidence = collect_unsigned_evidence(
                repository=args.repository,
                pull_request=args.pull_request,
                ruleset_id=args.ruleset_id,
                workflow_run_id=args.workflow_run_id,
                key_id=args.key_id,
                key_version=args.key_version,
            )
            _write_private_output(args.output, _canonical(evidence).encode("ascii"))
        elif args.phase == "sign":
            if args.output.exists():
                raise ValueError("offline signed-envelope output already exists")
            sign_collected_evidence(args.evidence, args.private_key, args.output)
            os.chmod(args.output, 0o600)
        else:
            encoded = os.environ.get("AVIATO_PRIVILEGED_REVIEW_ENVELOPE_BASE64", "")
            if (
                not encoded
                or len(encoded) > _MAX_ENVELOPE_BASE64_CHARS
                or re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", encoded) is None
            ):
                raise ValueError("signed envelope input is absent, oversized, or non-canonical base64url")
            try:
                raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
                envelope = json.loads(raw)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("signed envelope input is invalid") from exc
            if not isinstance(envelope, dict) or raw != _canonical(envelope).encode("ascii"):
                raise ValueError("signed envelope input is not exact canonical JSON")
            errors = verify_signed_envelope(envelope)
            if errors:
                raise ValueError("signed envelope failed fresh verification: " + "; ".join(errors))
            _write_private_output(args.output, raw)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
