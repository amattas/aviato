from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

# Explicit re-export (`as run`): github_platform (and test monkeypatches) access this
# helper as a real `aviato.github.run` module attribute.
from .command import run as run

# §5.5 (finding 30): rate-limit responses are tolerated and RETRIED (bounded), so a
# scheduled fleet run doesn't fail outright on the first 403/429 throttle; a
# persistent throttle then surfaces as the normal loud failure. Only OBVIOUS
# throttle shapes retry — auth/4xx semantics must stay immediate.
_RATE_LIMIT_MARKERS = ("rate limit", "ratelimit", "secondary rate", "abuse detection", "http 429")
_RATE_LIMIT_ATTEMPTS = 3
_RATE_LIMIT_BASE_SLEEP_SECONDS = 2.0


def _run_gh_read(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a gh READ with bounded rate-limit retry (§5.5, finding 30)."""
    result = run(args, check=False)
    for attempt in range(1, _RATE_LIMIT_ATTEMPTS):
        if result.returncode == 0 or not any(m in result.stderr.lower() for m in _RATE_LIMIT_MARKERS):
            return result
        time.sleep(_RATE_LIMIT_BASE_SLEEP_SECONDS * (2 ** (attempt - 1)))
        result = run(args, check=False)
    return result


def _branch_seg(branch: str) -> str:
    """Percent-encode a branch name for an API path (R2-2/§2.7).

    GitHub's branch endpoints accept ``/`` in a branch name (e.g. ``release/main``) as part of the
    route, so ``/`` is left safe; every OTHER special char (``?``, ``#``, space, …) is encoded so a
    branch name cannot alter the endpoint path it's interpolated into."""
    return quote(branch, safe="/")


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
    result = _run_gh_read(["gh", "api", endpoint])
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
    result = _run_gh_read(["gh", "api", "--paginate", "--slurp", endpoint])
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
    result = _run_gh_read(["gh", "api", endpoint])
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


def gh_json_paginated_optional(endpoint: str, *, default: Any = None) -> Any:
    """Paginated read (C12-R3-2/N2) of a LIST endpoint that may legitimately 404, fail-closed (§2.7).

    Combines ``gh_json_paginated``'s ``--paginate --slurp`` (so a later-page entry — a stale
    consent-bearing issue, an active branch rule, a tag ruleset — can never hide behind page 1) with
    ``gh_json_optional``'s posture: a genuine 404 returns ``default``; any other error raises.
    """
    result = _run_gh_read(["gh", "api", "--paginate", "--slurp", endpoint])
    if result.returncode != 0:
        if "http 404" in result.stderr.lower():
            return default
        raise GitHubAPIError(endpoint, result.returncode, result.stderr)
    if not result.stdout.strip():
        return default
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubAPIError(endpoint, result.returncode, f"invalid JSON response: {exc}") from exc
    if isinstance(pages, list) and pages and all(isinstance(page, list) for page in pages):
        return [item for page in pages for item in page]
    return pages


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


def repo_merge_methods(slug: str) -> dict[str, Any]:
    """Return the repo's top-level PR merge-method toggles (allow_merge_commit /
    allow_squash_merge / allow_rebase_merge) from the repo GET, failing closed on an
    ambiguous read (§2.7) — only keys GitHub actually reports are kept."""
    repo = gh_json_optional(f"repos/{slug}", default={})
    if not isinstance(repo, dict):
        return {}
    return {key: repo[key] for key in ("allow_merge_commit", "allow_squash_merge", "allow_rebase_merge") if key in repo}


def protected_environment_has_reviewers(slug: str, environment: str) -> bool | None:
    """True iff a GitHub Environment exists for ``slug`` with at least one required reviewer (§17).

    R7-3-APPSTORE-ENV: §17 mandates the App Store deploy (and any similarly-privileged release) run
    in a PROTECTED environment with a required reviewer. Returns None on an ambiguous read (404,
    non-dict, missing fields) so the doctor surfaces "unknown" rather than mis-reporting (§5.14).
    A clean determinate True/False is only emitted when the API returns a parseable environment with
    a countable reviewers list.
    """
    env = gh_json_optional(f"repos/{slug}/environments/{environment}", default=None)
    if not isinstance(env, dict):
        return None  # 404 (ambiguous: env absent vs no-perms) or non-dict — unknown per §5.14
    rules = env.get("protection_rules")
    if not isinstance(rules, list):
        return None  # schema drift — unknown, not a determinate "no reviewers"
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "required_reviewers":
            continue
        reviewers = rule.get("reviewers")
        if isinstance(reviewers, list) and len(reviewers) > 0:
            return True
    return False  # environment exists + parseable rules but no required-reviewer rule (real "no")


def pages_source_is_actions(slug: str) -> bool | None:
    """True iff the repo has Pages enabled with the GitHub Actions source (§13.3).

    R6-2-§17-PROBE: §17 lists this as remote-probeable. Returns None on an ambiguous read so
    `doctor` can surface "unable to determine" rather than mis-report "absent" (§5.14).

    R7-3-PAGES-§5.14: a 404 from ``repos/{slug}/pages`` is NOT a determinate "Pages off" — the
    GitHub API conflates "Pages not configured" with "token lacks Pages-read permission" and "repo
    not visible to the token", so the only honest mapping is "unknown" (None). Returning False
    would violate §5.14's "absence/unreadable reads as broken, not clean" — a private repo whose
    operator forgot to grant Pages-read would read clean-disabled despite actually being enabled.
    R7-3-PAGES-SCHEMA: same posture for a present dict that lacks the ``build_type`` field (schema
    drift / older API version) — unknown, not no.
    """
    pages = gh_json_optional(f"repos/{slug}/pages", default=None)
    if not isinstance(pages, dict):
        return None  # 404 (ambiguous: off vs no-perms vs invisible) or non-dict response
    build_type = pages.get("build_type")
    if build_type is None:
        return None  # field absent — unknown, never a determinate "no"
    return bool(build_type == "workflow")


def active_branch_rules(slug: str, branch: str) -> list[dict[str, Any]]:
    # Fail closed on an ambiguous read (§2.7): only a genuine 404 is empty. N2: paginate — a repo with
    # >30 active branch rules must not hide a later-page rule from the read/apply guards.
    response = gh_json_paginated_optional(f"repos/{slug}/rules/branches/{_branch_seg(branch)}", default=[])
    return response if isinstance(response, list) else []


def classic_branch_protection(slug: str, branch: str) -> dict[str, Any]:
    response = gh_json_optional(f"repos/{slug}/branches/{_branch_seg(branch)}/protection", default={})
    return response if isinstance(response, dict) else {}


def tag_ruleset_names(slug: str) -> list[str]:
    # Fail closed on an ambiguous read (§2.7): only a genuine 404 is empty, so an
    # auth/5xx/rate-limit error raises rather than masquerading as "no tag ruleset". N2: paginate so a
    # later-page tag ruleset is not invisible.
    response = gh_json_paginated_optional(f"repos/{slug}/rulesets?targets=tag", default=[])
    if not isinstance(response, list):
        return []
    names = [item.get("name") for item in response if isinstance(item, dict) and item.get("target") == "tag"]
    return [name for name in names if isinstance(name, str)]


def repository_ruleset(slug: str, ruleset_id: Any) -> dict[str, Any]:
    """Full payload (incl. rules + conditions) of one ruleset by id (§5.6 content drift).

    The list endpoint returns only summaries (no rules), so content drift needs this per-id GET.
    Fails CLOSED (no allow_error): an auth/5xx must raise, never read as an empty/clean ruleset.
    """
    response = gh_json(f"repos/{slug}/rulesets/{ruleset_id}")
    return response if isinstance(response, dict) else {}


def repository_rulesets(slug: str) -> list[dict[str, Any]]:
    # Paginate: upsert_ruleset decides PUT-vs-POST by finding an existing ruleset by
    # name here, so a match on a later page must not be hidden (else it POSTs a duplicate).
    response = gh_json_paginated(f"repos/{slug}/rulesets", default=[])
    return response if isinstance(response, list) else []


def upsert_ruleset(slug: str, payload: dict[str, Any], *, apply: bool) -> str:
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("ruleset payload must include a non-empty name")
    # N1 (cycle 11): match the live ruleset by (name, target), not name alone. Drift detection keys
    # by (name, target) (rulesets.drifted_ruleset_names), so a name-only match here could UPDATE a
    # same-named ruleset on the WRONG target (e.g. overwrite the branch ruleset with a tag payload)
    # instead of creating the missing one. The rendered payload always carries `target`.
    target = payload.get("target")
    same_name = [r for r in repository_rulesets(slug) if isinstance(r, dict) and r.get("name") == name]
    existing_id = None
    for ruleset in same_name:  # prefer an exact (name, target) match
        if ruleset.get("target") == target:
            existing_id = ruleset.get("id")
            break
    else:
        # C12-2: GitHub's ruleset LIST summary may OMIT `target`. A same-name candidate whose target is
        # absent/None can only be THIS ruleset (it cannot be on a different target if the field is not
        # returned), so fall back to it rather than POSTing a duplicate (and risking a 422). When the
        # list DOES carry target, this fallback is never reached. Avoids a name-only match that would
        # overwrite a genuinely different-target ruleset.
        for ruleset in same_name:
            if ruleset.get("target") is None:
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
