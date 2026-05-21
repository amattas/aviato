"""GitHub binding for the agnostic :class:`aviato.core.ports.Platform` (§2.14).

This is the day-zero hosting-platform binding. It lives outside ``aviato.core``
(the core depends only on the Protocol) and composes the gh-backed helpers in
:mod:`aviato.github`. The reporting/read methods are low-privilege; the only
mutating method, ``apply_settings``, is reached solely through the §5.7 gated
path. Live behavior is operator-verified (§9.2/§8.10); the response-mapping
logic below is unit-tested.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from . import github
from .core.ports import Issue


def map_branch_settings(rules: list[dict[str, Any]], protection: dict[str, Any]) -> dict[str, Any]:
    """Map live default-branch rules/protection into a comparable settings map (§5.6, §2.9).

    Read-shaped platform data is reduced to the operator-relevant fields only; it
    is never replayed verbatim into a write.
    """
    pr_rule = next((r for r in rules if r.get("type") == "pull_request"), None)
    requires_pr = pr_rule is not None or protection.get("required_pull_request_reviews") is not None

    required_reviews = 0
    if pr_rule is not None:
        required_reviews = int(pr_rule.get("parameters", {}).get("required_approving_review_count", 0))
    else:
        classic = protection.get("required_pull_request_reviews") or {}
        required_reviews = int(classic.get("required_approving_review_count", 0))

    rules_nff = any(r.get("type") == "non_fast_forward" for r in rules)
    allow_force = protection.get("allow_force_pushes")
    classic_force_blocked = isinstance(allow_force, dict) and allow_force.get("enabled") is not True
    block_force_push = rules_nff or classic_force_blocked

    block_deletion = any(r.get("type") == "deletion" for r in rules)

    return {
        "requires_pull_request": requires_pr,
        "required_reviews": required_reviews,
        "block_force_push": block_force_push,
        "block_deletion": block_deletion,
    }


class GitHubPlatform:
    """Concrete :class:`aviato.core.ports.Platform` over the ``gh`` CLI."""

    def read_settings(self, repo: str) -> dict[str, Any]:
        branch = github.default_branch(repo)
        if not branch:
            return {}
        rules = github.active_branch_rules(repo, branch)
        protection = github.classic_branch_protection(repo, branch)
        return {"default_branch": map_branch_settings(rules, protection)}

    def get_issue(self, repo: str, key: str) -> Issue | None:
        issues = github.gh_json(f"repos/{repo}/issues?state=all&labels={key}", default=[], allow_error=True)
        if not isinstance(issues, list) or not issues:
            return None
        head = issues[0]
        return Issue(key=key, open=head.get("state") == "open")

    def open_or_update_issue(self, repo: str, key: str, title: str, body: str) -> str:
        existing = github.gh_json(f"repos/{repo}/issues?state=open&labels={key}", default=[], allow_error=True)
        if isinstance(existing, list) and existing:
            number = existing[0]["number"]
            self._gh_input(["--method", "PATCH", f"repos/{repo}/issues/{number}"], {"body": body})
            return str(number)
        self._gh_input(["--method", "POST", f"repos/{repo}/issues"], {"title": title, "body": body, "labels": [key]})
        return key

    def comment_issue(self, repo: str, key: str, body: str) -> None:
        existing = github.gh_json(f"repos/{repo}/issues?state=all&labels={key}", default=[], allow_error=True)
        if isinstance(existing, list) and existing:
            number = existing[0]["number"]
            self._gh_input(["--method", "POST", f"repos/{repo}/issues/{number}/comments"], {"body": body})

    def open_or_update_proposal(self, repo: str, branch: str, title: str, files: dict[str, str], body: str) -> str:
        # Branch/PR creation is performed by the consumer-side workflow that holds
        # the working tree; this binding records the intended proposal identity.
        return branch

    def apply_settings(self, repo: str, payload: dict[str, Any]) -> None:
        branch = github.default_branch(repo)
        self._gh_input(["--method", "PUT", f"repos/{repo}/branches/{branch}/protection"], payload)

    @staticmethod
    def _gh_input(args: list[str], payload: dict[str, Any]) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = Path(handle.name)
        try:
            github.run(["gh", "api", *args, "--input", str(path)])
        finally:
            path.unlink(missing_ok=True)
