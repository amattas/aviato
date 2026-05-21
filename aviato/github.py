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


def default_branch(slug: str) -> str:
    response = gh_json(f"repos/{slug}")
    if not isinstance(response, dict):
        return ""
    value = response.get("default_branch")
    return value if isinstance(value, str) else ""


def active_branch_rules(slug: str, branch: str) -> list[dict[str, Any]]:
    response = gh_json(f"repos/{slug}/rules/branches/{branch}", default=[], allow_error=True)
    return response if isinstance(response, list) else []


def classic_branch_protection(slug: str, branch: str) -> dict[str, Any]:
    response = gh_json(f"repos/{slug}/branches/{branch}/protection", default={}, allow_error=True)
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
