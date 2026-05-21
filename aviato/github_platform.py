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


class UnmodeledProtectionError(RuntimeError):
    """Raised when a settings apply would drop live protections the model doesn't cover."""


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


def nonhuman_edit_after_grant(timeline: list[dict[str, Any]], diff_id: str) -> bool:
    """True if a non-human actor touched the issue after the consent grant (§2.8/§5.7).

    Finds the latest grant of ``aviato-consent:<diff_id>`` and reports whether any
    later timeline entry was performed by an actor whose type is not ``User`` (a
    Bot/App/unknown actor). Entries with no actor are system events and ignored.
    """
    grant_label = f"{CONSENT_LABEL_PREFIX}{diff_id}"
    grant_index = -1
    for i, entry in enumerate(timeline):
        if entry.get("event") == "labeled" and (entry.get("label") or {}).get("name") == grant_label:
            grant_index = i
    if grant_index < 0:
        return False
    for entry in timeline[grant_index + 1 :]:
        actor = entry.get("actor")
        # Fail closed (§2.7): an actor present on a post-grant edit whose type is
        # not exactly "User" — including an ambiguous/unknown type — counts as a
        # non-human edit and voids consent. Actorless system events are ignored.
        if isinstance(actor, dict) and actor.get("type") != "User":
            return True
    return False


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
    """Map live default-branch rules/protection into the flat comparable settings map (§5.6, §2.9).

    Read-shaped platform data is reduced to exactly the keys the desired baseline
    uses (so a compliant repo compares clean), never replayed verbatim into a
    write. Returns the same flat shape the resolved ``default_branch`` map carries.
    """
    pr_rule = next((r for r in rules if r.get("type") == "pull_request"), None)
    pr_params = pr_rule.get("parameters", {}) if pr_rule else {}
    classic_reviews = protection.get("required_pull_request_reviews") or {}
    requires_pr = pr_rule is not None or protection.get("required_pull_request_reviews") is not None

    if pr_rule is not None:
        required_reviews = int(pr_params.get("required_approving_review_count", 0))
        dismiss_stale = bool(pr_params.get("dismiss_stale_reviews_on_push", False))
        require_threads = bool(pr_params.get("required_review_thread_resolution", False))
    else:
        required_reviews = int(classic_reviews.get("required_approving_review_count", 0))
        dismiss_stale = bool(classic_reviews.get("dismiss_stale_reviews", False))
        require_threads = bool((protection.get("required_conversation_resolution") or {}).get("enabled", False))

    rules_nff = any(r.get("type") == "non_fast_forward" for r in rules)
    allow_force = protection.get("allow_force_pushes")
    classic_force_blocked = isinstance(allow_force, dict) and allow_force.get("enabled") is not True
    block_force_push = rules_nff or classic_force_blocked

    rules_deletion = any(r.get("type") == "deletion" for r in rules)
    allow_del = protection.get("allow_deletions")
    classic_deletion_blocked = isinstance(allow_del, dict) and allow_del.get("enabled") is not True
    block_deletion = rules_deletion or classic_deletion_blocked

    return {
        "requires_pull_request": requires_pr,
        "required_reviews": required_reviews,
        "dismiss_stale_reviews": dismiss_stale,
        "require_thread_resolution": require_threads,
        "block_force_push": block_force_push,
        "block_deletion": block_deletion,
    }


def map_security_settings(security_and_analysis: dict[str, Any]) -> dict[str, Any]:
    """Map the live ``security_and_analysis`` block to the flat security settings (§2.13).

    Only the toggles GitHub actually reports are returned; an undeterminable one is
    omitted (so it shows as additive "to enable", never a false destructive). Code
    scanning is delivered by the CodeQL **workflow** (a managed artifact, covered by
    file drift), so it is not read here as a repo toggle.
    """
    out: dict[str, Any] = {}

    def _enabled(key: str) -> bool:
        value = security_and_analysis.get(key)
        return isinstance(value, dict) and value.get("status") == "enabled"

    if "secret_scanning" in security_and_analysis:
        out["secret_scanning"] = _enabled("secret_scanning")
    if "secret_scanning_push_protection" in security_and_analysis:
        out["secret_push_protection"] = _enabled("secret_scanning_push_protection")
    if "dependabot_security_updates" in security_and_analysis:
        out["dependency_scanning"] = _enabled("dependabot_security_updates")
    return out


def to_security_payload(desired: dict[str, Any]) -> dict[str, Any]:
    """Build a ``security_and_analysis`` PATCH from the flat desired settings (§2.9)."""
    mapping = {
        "secret_scanning": "secret_scanning",
        "secret_push_protection": "secret_scanning_push_protection",
        "dependency_scanning": "dependabot_security_updates",
    }
    payload: dict[str, Any] = {}
    for desired_key, api_key in mapping.items():
        if desired_key in desired:
            payload[api_key] = {"status": "enabled" if desired[desired_key] else "disabled"}
    return payload


def to_branch_protection_payload(desired: dict[str, Any]) -> dict[str, Any]:
    """Translate the flat desired settings into a complete branch-protection PUT payload (§2.9).

    The PUT endpoint replaces protection wholesale, so the full desired state is
    sent in the API's own shape (all required keys present, nullable where unset)
    — not the internal key names, and not a partial diff that would drop other
    protections.
    """
    reviews: dict[str, Any] | None = None
    if desired.get("requires_pull_request"):
        reviews = {
            "required_approving_review_count": int(desired.get("required_reviews", 1)),
            "dismiss_stale_reviews": bool(desired.get("dismiss_stale_reviews", False)),
            "require_code_owner_reviews": False,
        }
    return {
        "required_status_checks": None,
        "enforce_admins": True,
        "required_pull_request_reviews": reviews,
        "restrictions": None,
        "allow_force_pushes": not bool(desired.get("block_force_push", False)),
        "allow_deletions": not bool(desired.get("block_deletion", False)),
        "required_conversation_resolution": bool(desired.get("require_thread_resolution", False)),
    }


class GitHubPlatform:
    """Concrete :class:`aviato.core.ports.Platform` over the ``gh``/``git`` CLIs."""

    def __init__(self, workdir: Path | str = ".") -> None:
        self.workdir = Path(workdir)

    def read_settings(self, repo: str) -> dict[str, Any]:
        # Returns the flat default-branch settings map, matching the desired map
        # the CLI passes (resolved.settings["default_branch"]) so the diff compares
        # like-for-like (§5.6).
        branch = github.default_branch(repo)
        if not branch:
            return {}
        rules = github.active_branch_rules(repo, branch)
        protection = github.classic_branch_protection(repo, branch)
        security = map_security_settings(github.repo_security_settings(repo))
        # Flat merge: branch-protection fields + repo security toggles, matching the
        # flat desired map the CLI passes (so security drift is visible, §5.6/§2.13).
        return {**map_branch_settings(rules, protection), **security}

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
        raw_timeline = timeline if isinstance(timeline, list) else []
        return Issue(
            key=key,
            open=is_open,
            consent_diff_id=grant.diff_id,
            consent_actor_type=grant.actor_type,
            consent_role=role,
            consent_role_lookup_ok=role_ok,
            edited_by_nonhuman_since_grant=nonhuman_edit_after_grant(raw_timeline, grant.diff_id),
        )

    def probe_health(self, repo: str) -> tuple[bool | None, bool | None]:
        """Probe issue-channel availability and scan-heartbeat presence (§5.4/§5.14).

        Returns ``(issue_channel_available, scan_heartbeat_present)``. A value is
        None when it cannot be determined (e.g. the API call failed) — and a None
        heartbeat reads as broken, never clean (§5.14). Best-effort: a failed probe
        does not raise (doctor is a read-only health report).
        """
        issue_channel: bool | None = None
        heartbeat: bool | None = None
        try:
            repo_data = github.gh_json_optional(f"repos/{repo}", default=None)
            if isinstance(repo_data, dict) and "has_issues" in repo_data:
                issue_channel = bool(repo_data["has_issues"])
            # Read the per-run heartbeat the security baseline EMITS (§5.14) — the
            # presence of a recent `aviato-security-heartbeat` artifact — not a stale
            # CodeQL analysis that could read "present" even if this run never ran.
            artifacts = github.gh_json_optional(
                f"repos/{repo}/actions/artifacts?name=aviato-security-heartbeat&per_page=1", default=None
            )
            if isinstance(artifacts, dict) and "artifacts" in artifacts:
                items = artifacts["artifacts"]
                heartbeat = bool(items) and not all(a.get("expired") for a in items)
        except github.GitHubAPIError:
            pass  # ambiguous read → leave unknown (None)
        return issue_channel, heartbeat

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
        """Write the regenerated files onto an identity-keyed branch and open/update a PR (§5.5).

        Runs in the checked-out working tree (``workdir``). Requires ``contents:
        write`` (to push the branch) and ``pull-requests: write``. Re-runs converge
        on the same branch, so the existing PR is simply updated by the push.
        """
        base = github.default_branch(repo) or "main"
        owner = repo.split("/", 1)[0]

        for output_path, content in files.items():
            target = self.workdir / output_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        self._git("switch", "-C", branch)
        self._git("add", "--", *files.keys())
        self._git(
            "-c",
            "user.name=aviato-bot",
            "-c",
            "user.email=aviato-bot@users.noreply.github.com",
            "commit",
            "-m",
            title,
        )
        self._git("push", "--force", "origin", branch)

        existing = github.gh_json(f"repos/{repo}/pulls?head={owner}:{branch}&state=open", default=[], allow_error=True)
        if not (isinstance(existing, list) and existing):
            self._gh("pr", "create", "--repo", repo, "--head", branch, "--base", base, "--title", title, "--body", body)
        return branch

    def _git(self, *args: str) -> None:
        github.run(["git", *args], cwd=self.workdir)

    def _gh(self, *args: str) -> None:
        github.run(["gh", *args], cwd=self.workdir)

    def apply_settings(self, repo: str, payload: dict[str, Any]) -> None:
        # ``payload`` is the flat desired default-branch state; translate it to the
        # branch-protection API shape before the PUT (§2.9). The PUT replaces
        # protection wholesale, so FAIL CLOSED if the live branch carries protections
        # the desired model does not cover (required status checks / push
        # restrictions): silently dropping them would mutate state the operator never
        # saw or consented to (§2.4/§5.7).
        branch = github.default_branch(repo)
        live = github.classic_branch_protection(repo, branch)
        unmodeled = [k for k in ("required_status_checks", "restrictions") if live.get(k)]
        if unmodeled:
            raise UnmodeledProtectionError(
                f"refusing to PUT branch protection on {repo}@{branch}: it carries unmodeled "
                f"protection(s) {unmodeled} that this reconcile does not manage and would drop. "
                f"Reconcile those manually, then re-run."
            )
        api_payload = to_branch_protection_payload(payload)
        self._gh_input(["--method", "PUT", f"repos/{repo}/branches/{branch}/protection"], api_payload)

        # Apply the repo-level security toggles (§2.13) when present in the desired set.
        security_payload = to_security_payload(payload)
        if security_payload:
            self._gh_input(["--method", "PATCH", f"repos/{repo}"], {"security_and_analysis": security_payload})

    @staticmethod
    def _gh_input(args: list[str], payload: dict[str, Any]) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = Path(handle.name)
        try:
            github.run(["gh", "api", *args, "--input", str(path)])
        finally:
            path.unlink(missing_ok=True)
