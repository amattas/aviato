from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .command import run


class GitHubAPIError(RuntimeError):
    def __init__(self, endpoint: str, returncode: int, stderr: str) -> None:
        self.endpoint = endpoint
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"gh api {endpoint} failed with exit code {returncode}: {self.stderr}")


def gh_json(endpoint: str, *, default: Any = None, allow_error: bool = False) -> Any:
    result = run(["gh", "api", endpoint], check=False)
    if result.returncode != 0:
        if allow_error:
            return default
        raise GitHubAPIError(endpoint, result.returncode, result.stderr)
    if not result.stdout.strip():
        return default
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubAPIError(endpoint, result.returncode, f"invalid JSON response: {exc}") from exc


def gh_json_paginated(endpoint: str, *, default: Any = None, allow_error: bool = False) -> Any:
    """Fetch an endpoint following pagination, returning a single combined array.

    Uses ``gh api --paginate --slurp`` so a long resource (e.g. a tracking issue's
    full event timeline) is read in full — a later page cannot hide a revoke
    (§2.8/§6.4). Falls back to ``default`` on error when ``allow_error``.
    """
    result = run(["gh", "api", "--paginate", "--slurp", endpoint], check=False)
    if result.returncode != 0:
        if allow_error:
            return default
        raise GitHubAPIError(endpoint, result.returncode, result.stderr)
    if not result.stdout.strip():
        return default
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubAPIError(endpoint, result.returncode, f"invalid JSON response: {exc}") from exc
    # --slurp wraps each page's array in an outer array; flatten to one list.
    if isinstance(pages, list) and pages and all(isinstance(page, list) for page in pages):
        return [item for page in pages for item in page]
    return pages


def gh_json_optional(endpoint: str, *, default: Any = None) -> Any:
    """Read an endpoint that may legitimately 404, failing CLOSED on ambiguity (§2.7).

    A genuine 404 (the resource does not exist — e.g. a branch with no protection)
    returns ``default``. Any OTHER error (auth, rate limit, 5xx, network) raises,
    so drift/reconcile never computes from a falsely-"unprotected" live state.
    """
    result = run(["gh", "api", endpoint], check=False)
    if result.returncode != 0:
        stderr = result.stderr.lower()
        if "http 404" in stderr or "not found" in stderr or "no such" in stderr:
            return default
        raise GitHubAPIError(endpoint, result.returncode, result.stderr)
    if not result.stdout.strip():
        return default
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubAPIError(endpoint, result.returncode, f"invalid JSON response: {exc}") from exc


def default_branch(slug: str) -> str:
    response = gh_json(f"repos/{slug}")
    if not isinstance(response, dict):
        return ""
    value = response.get("default_branch")
    return value if isinstance(value, str) else ""


def repo_security_settings(slug: str) -> dict[str, Any]:
    """Return the repo's ``security_and_analysis`` block (secret scanning, push
    protection, Dependabot), failing closed on an ambiguous read (§2.7)."""
    repo = gh_json_optional(f"repos/{slug}", default={})
    sa = repo.get("security_and_analysis") if isinstance(repo, dict) else None
    return sa if isinstance(sa, dict) else {}


def active_branch_rules(slug: str, branch: str) -> list[dict[str, Any]]:
    # Fail closed on an ambiguous read (§2.7): only a genuine 404 is empty.
    response = gh_json_optional(f"repos/{slug}/rules/branches/{branch}", default=[])
    return response if isinstance(response, list) else []


def classic_branch_protection(slug: str, branch: str) -> dict[str, Any]:
    response = gh_json_optional(f"repos/{slug}/branches/{branch}/protection", default={})
    return response if isinstance(response, dict) else {}


def tag_ruleset_names(slug: str) -> list[str]:
    response = gh_json(f"repos/{slug}/rulesets?targets=tag", default=[], allow_error=True)
    if not isinstance(response, list):
        return []
    names = [item.get("name") for item in response if isinstance(item, dict) and item.get("target") == "tag"]
    return [name for name in names if isinstance(name, str)]


def repository_rulesets(slug: str) -> list[dict[str, Any]]:
    response = gh_json(f"repos/{slug}/rulesets")
    return response if isinstance(response, list) else []


def upsert_ruleset(slug: str, payload: dict[str, Any], *, apply: bool) -> str:
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("ruleset payload must include a non-empty name")

    existing_id = None
    for ruleset in repository_rulesets(slug):
        if ruleset.get("name") == name:
            existing_id = ruleset.get("id")
            break

    if not apply:
        if existing_id:
            return f"DRY RUN: would update {name} on {slug} (ruleset {existing_id})"
        return f"DRY RUN: would create {name} on {slug}"

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        handle.write("\n")
        payload_path = Path(handle.name)

    try:
        if existing_id:
            run(["gh", "api", "--method", "PUT", f"repos/{slug}/rulesets/{existing_id}", "--input", str(payload_path)])
            return f"Updated {name} on {slug}"
        run(["gh", "api", "--method", "POST", f"repos/{slug}/rulesets", "--input", str(payload_path)])
        return f"Created {name} on {slug}"
    finally:
        payload_path.unlink(missing_ok=True)
