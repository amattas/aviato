from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from .ports import Platform
from .settingsdrift import SettingsDiff, classify_settings

Status = Literal["clean", "resolved", "reported"]


@dataclass(frozen=True)
class SettingsDriftOutcome:
    status: Status
    destructive: bool = False
    consent_voided: bool = False
    diff_id: str | None = None


def diff_identity(diff: SettingsDiff) -> str:
    """A stable, content-bound identity for a settings diff (§6.4 consent binding).

    Hashes the changed keys together with their classification AND their concrete
    desired/live values, so consent for ``required_reviews: 1 -> 2`` does not match
    ``required_reviews: 1 -> 5`` (a different change needs different consent, §8.3).
    """
    payload = {
        key: {
            "kind": kind,
            "desired": diff.values.get(key, {}).get("desired"),
            "live": diff.values.get(key, {}).get("live"),
        }
        for key, kind in diff.changes.items()
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _render_change(diff: SettingsDiff, key: str) -> str:
    kind = diff.changes[key]
    vals = diff.values.get(key, {})
    return f"- {key}: {kind} ({vals.get('live')!r} -> {vals.get('desired')!r})"


def _render_issue_body(diff: SettingsDiff, repo: str, issue_key: str) -> str:
    diff_id = diff_identity(diff)
    lines = ["Aviato detected settings drift.", "", f"Diff id: {diff_id}", "", "Changes (classified):"]
    lines += [_render_change(diff, key) for key in sorted(diff.changes)]
    lines += [
        "",
        f"To apply, an operator checks out {repo} and, from the repository root, runs:",
        f"    aviato reconcile . {issue_key} --confirm {diff_id}",
        "",
        "(reconcile takes the LOCAL repository path; OWNER/REPO is read from its remote. "
        "It re-reads live settings at apply time, re-classifies, and applies only if the "
        "recomputed diff still matches the id you confirmed — otherwise it aborts.)",
        "",
        "No settings mutation has been performed (report-only, §5.6).",
    ]
    return "\n".join(lines)


def run_settings_drift(
    platform: Platform,
    *,
    repo: str,
    desired_settings: dict[str, Any],
    issue_key: str,
) -> SettingsDriftOutcome:
    """Report (never apply) settings drift (§5.6).

    Reads live settings, classifies the diff (additive/destructive, ambiguous =
    destructive), and on a non-empty diff opens/updates the tracking issue with
    the diff and the operator reconcile command. An empty diff comments "resolved
    — verify before closing" on an open issue (never auto-closes). If a prior
    consent record is bound to a different diff, it is voided with a comment. The
    issue channel being unavailable fails loud (the platform raises). No settings
    mutation is ever performed.
    """
    live = platform.read_settings(repo)
    diff = classify_settings(desired=desired_settings, live=live)
    issue = platform.get_issue(repo, issue_key)

    if not diff.changes:
        if issue is not None and issue.open:
            platform.comment_issue(
                repo, issue_key, "Drift resolved — verify before closing (Aviato will not auto-close)."
            )
            return SettingsDriftOutcome(status="resolved")
        return SettingsDriftOutcome(status="clean")

    current_id = diff_identity(diff)
    consent_voided = False
    if issue is not None and issue.consent_diff_id is not None and issue.consent_diff_id != current_id:
        platform.comment_issue(
            repo, issue_key, "Reported diff changed since consent was granted; prior consent is voided."
        )
        consent_voided = True

    platform.open_or_update_issue(repo, issue_key, "Aviato: settings drift", _render_issue_body(diff, repo, issue_key))
    return SettingsDriftOutcome(
        status="reported", destructive=diff.destructive, consent_voided=consent_voided, diff_id=current_id
    )
