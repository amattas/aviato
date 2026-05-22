from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .command import run

# The settings-drift automation (§5.6) supplies an operator's admin-scoped READ token here
# so branch-protection/ruleset reads — which the platform's ephemeral workflow token cannot
# perform — succeed. It is read-only IN USE: scoped (via settings_read_token_scope) to those
# reads alone, never to the issue WRITES, which run under the ambient platform token. This is
# what keeps the §11.2/§14 "no write-capable stored secret" posture honest (the stored secret
# performs no mutation; apply is the separate §5.7 operator-gated path).
SETTINGS_READ_TOKEN_ENV = "AVIATO_SETTINGS_READ_TOKEN"


@contextmanager
def settings_read_token_scope() -> Iterator[None]:
    """Point ``gh`` at the admin READ token (if supplied) for the duration of a read block.

    Temporarily sets ``GH_TOKEN`` to ``$AVIATO_SETTINGS_READ_TOKEN`` so the settings reads use
    the read-only admin token, then restores the prior value so subsequent issue WRITES use the
    ambient platform token. A no-op when the read token is unset (settings-drift then skips
    fail-closed on the unreadable admin surface, §5.6).
    """
    token = os.environ.get(SETTINGS_READ_TOKEN_ENV)
    if not token:
        yield
        return
    previous = os.environ.get("GH_TOKEN")
    os.environ["GH_TOKEN"] = token
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("GH_TOKEN", None)
        else:
            os.environ["GH_TOKEN"] = previous


class GitHubAPIError(RuntimeError):
    def __init__(self, endpoint: str, returncode: int, stderr: str) -> None:
        self.endpoint = endpoint
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"gh api {endpoint} failed with exit code {returncode}: {self.stderr}")


class SettingsReadError(GitHubAPIError):
    """A live protected-settings read failed (e.g. the token lacks the admin scope).

    Distinct subclass so settings-drift can fail closed by **skipping** a settings
    read it cannot perform (§5.6) WITHOUT also swallowing an issue-channel failure —
    which §5.6 requires to fail loud. It remains a :class:`GitHubAPIError`, so any
    caller that does not care about the distinction (e.g. reconcile, which fails on
    any read error) keeps its existing behavior.
    """


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
        # Distinguish a genuine 404 ONLY by the HTTP status `gh` appends (``(HTTP 404)``).
        # Keying off free-text like "not found"/"no such" would misread a 403/5xx whose
        # body merely contains those words as an empty 404 — re-opening the §2.7 fail-OPEN.
        if "http 404" in result.stderr.lower():
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


def is_archived(slug: str) -> bool | None:
    """Whether the repository is archived (§5.11 fleet-scan skip), or None if unreadable.

    None — not False — on an ambiguous/absent read, so the fleet scan never silently SKIPS a
    repo it could not classify (skipping would hide it from the operator's read-only scan). A
    genuine 404 (repo gone) also reads as None.
    """
    repo = gh_json_optional(f"repos/{slug}", default=None)
    if not isinstance(repo, dict) or "archived" not in repo:
        return None
    return bool(repo["archived"])


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
    # Fail closed on an ambiguous read (§2.7): only a genuine 404 is empty, so an
    # auth/5xx/rate-limit error raises rather than masquerading as "no tag ruleset".
    response = gh_json_optional(f"repos/{slug}/rulesets?targets=tag", default=[])
    if not isinstance(response, list):
        return []
    names = [item.get("name") for item in response if isinstance(item, dict) and item.get("target") == "tag"]
    return [name for name in names if isinstance(name, str)]


def repository_rulesets(slug: str) -> list[dict[str, Any]]:
    # Paginate: upsert_ruleset decides PUT-vs-POST by finding an existing ruleset by
    # name here, so a match on a later page must not be hidden (else it POSTs a duplicate).
    response = gh_json_paginated(f"repos/{slug}/rulesets", default=[])
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
