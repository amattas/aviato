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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import github
from .core.ports import Issue

# A human grants consent by adding a label of this form to the tracking issue;
# the diff identity it authorizes is encoded after the prefix (§6.4).
CONSENT_LABEL_PREFIX = "aviato-consent:"


@dataclass(frozen=True)
class ConsentGrant:
    diff_id: str
    actor_type: str | None
    actor_login: str | None


def _label_events(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize GitHub timeline entries into label-event dicts for :func:`current_consent`."""
    events: list[dict[str, Any]] = []
    for entry in timeline:
        action = entry.get("event")
        if action not in ("labeled", "unlabeled"):
            continue
        label = entry.get("label") or {}
        actor = entry.get("actor") or {}
        events.append(
            {
                "action": action,
                "label": label.get("name", ""),
                "actor_type": actor.get("type"),
                "actor_login": actor.get("login"),
            }
        )
    return events


def current_consent(events: list[dict[str, Any]]) -> ConsentGrant | None:
    """Reduce a chronological list of label events to the active consent grant (§6.4).

    Each event is ``{"action": "labeled"|"unlabeled", "label": str,
    "actor_type": str|None, "actor_login": str|None}``. A ``labeled`` event with
    the consent prefix is a grant; a matching ``unlabeled`` is a revoke. The
    current consent is the most recent grant not later revoked. Reading the full
    (paginated) history is what prevents a later revoke from being missed.
    """
    active: dict[str, tuple[int, str | None, str | None]] = {}
    for seq, event in enumerate(events):
        label = event.get("label", "")
        if not isinstance(label, str) or not label.startswith(CONSENT_LABEL_PREFIX):
            continue
        diff_id = label[len(CONSENT_LABEL_PREFIX) :]
        if event.get("action") == "labeled":
            active[diff_id] = (seq, event.get("actor_type"), event.get("actor_login"))
        elif event.get("action") == "unlabeled":
            active.pop(diff_id, None)
    if not active:
        return None
    diff_id, (_, actor_type, actor_login) = max(active.items(), key=lambda item: item[1][0])
    return ConsentGrant(diff_id=diff_id, actor_type=actor_type, actor_login=actor_login)


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
        number = head.get("number")
        is_open = head.get("state") == "open"

        # Read the FULL (paginated) label-event history so a later revoke cannot
        # be missed (§2.8/§6.4), then reduce to the active consent grant.
        timeline = github.gh_json_paginated(f"repos/{repo}/issues/{number}/timeline", default=[], allow_error=True)
        events = _label_events(timeline if isinstance(timeline, list) else [])
        grant = current_consent(events)
        if grant is None:
            return Issue(key=key, open=is_open)

        role, role_ok = self._actor_role(repo, grant.actor_login)
        return Issue(
            key=key,
            open=is_open,
            consent_diff_id=grant.diff_id,
            consent_actor_type=grant.actor_type,
            consent_role=role,
            consent_role_lookup_ok=role_ok,
        )

    def _actor_role(self, repo: str, login: str | None) -> tuple[str | None, bool]:
        if not login:
            return None, False
        response = github.gh_json(f"repos/{repo}/collaborators/{login}/permission", default=None, allow_error=True)
        if not isinstance(response, dict):
            return None, False  # lookup failed → not authorized (§2.7)
        permission = response.get("permission")
        return (permission, True) if isinstance(permission, str) else (None, False)

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
