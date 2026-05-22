from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .ports import Platform
from .settingsdrift import SettingsDiff, classify_settings, diff_identity

# diff_identity now lives with SettingsDiff in settingsdrift; re-exported here so the
# §6.4 consent binding is available to both this flow and reconcile.py without a cycle.
__all__ = ["SettingsDriftOutcome", "diff_identity", "run_settings_drift"]

Status = Literal["clean", "resolved", "reported"]


@dataclass(frozen=True)
class SettingsDriftOutcome:
    status: Status
    destructive: bool = False
    consent_voided: bool = False
    diff_id: str | None = None
    # Desired rulesets absent from the live platform (§5.6). Report-only and remediated by
    # `apply-rulesets` (NOT the consent-gated §5.7 reconcile, which only writes branch/security).
    missing_rulesets: tuple[str, ...] = ()


def _render_change(diff: SettingsDiff, key: str) -> str:
    kind = diff.changes[key]
    vals = diff.values.get(key, {})
    return f"- {key}: {kind} ({vals.get('live')!r} -> {vals.get('desired')!r})"


def _render_issue_body(diff: SettingsDiff, missing_rulesets: list[str], repo: str, issue_key: str) -> str:
    lines = ["Aviato detected settings drift."]
    if diff.changes:
        diff_id = diff_identity(diff)
        lines += [
            "",
            f"Diff id: {diff_id}",
            "",
            "Branch-protection / security changes (classified):",
        ]
        lines += [_render_change(diff, key) for key in sorted(diff.changes)]
        lines += [
            "",
            f"To apply these, an operator checks out {repo} and, from the repository root, runs:",
            f"    aviato reconcile . {issue_key} --confirm {diff_id}",
            "",
            "(reconcile takes the LOCAL repository path; OWNER/REPO is read from its remote. "
            "It re-reads live settings at apply time, re-classifies, and applies only if the "
            "recomputed diff still matches the id you confirmed — otherwise it aborts.)",
        ]
    if missing_rulesets:
        # Rulesets are remediated by `apply-rulesets`, NOT reconcile (which writes only branch/
        # security). Reported here so a deleted/missing required ruleset is not invisible (§5.6).
        lines += [
            "",
            "Missing required rulesets (apply separately — NOT via reconcile):",
        ]
        lines += [f"- {name}" for name in sorted(missing_rulesets)]
        lines += [
            "",
            f"To restore them, an operator runs:    aviato apply-rulesets {repo} --apply",
        ]
    lines += ["", "No settings mutation has been performed (report-only, §5.6)."]
    return "\n".join(lines)


def run_settings_drift(
    platform: Platform,
    *,
    repo: str,
    desired_settings: dict[str, Any],
    issue_key: str,
    desired_rulesets: tuple[str, ...] = (),
) -> SettingsDriftOutcome:
    """Report (never apply) settings drift (§5.6).

    Reads live settings, classifies the diff (additive/destructive, ambiguous =
    destructive), and on a non-empty diff opens/updates the tracking issue with
    the diff and the operator reconcile command. An empty diff comments "resolved
    — verify before closing" on an open issue (never auto-closes). If a prior
    consent record is bound to a different diff, it is voided with a comment.

    Also reports **missing required rulesets** (§5.6): any name in
    ``desired_rulesets`` absent from the live platform is surfaced on the same
    tracking issue, remediated by ``apply-rulesets`` (NOT the consent-gated reconcile,
    which writes only branch/security). When ``desired_rulesets`` is empty the ruleset
    surface is not read at all, so behavior is unchanged for callers that omit it.

    The issue channel being unavailable fails loud (the platform raises); an
    unreadable settings surface fails closed as SettingsReadError. No settings
    mutation is ever performed.
    """
    live = platform.read_settings(repo)
    diff = classify_settings(desired=desired_settings, live=live)
    # Ruleset presence is admin-scoped like settings; only read it when rulesets are desired,
    # so callers that pass none keep the exact prior read/branch behavior (additive).
    live_rulesets = platform.read_ruleset_names(repo) if desired_rulesets else []
    missing_rulesets = [name for name in desired_rulesets if name not in live_rulesets]
    issue = platform.get_issue(repo, issue_key)

    if not diff.changes and not missing_rulesets:
        if issue is not None and issue.open:
            platform.comment_issue(
                repo, issue_key, "Drift resolved — verify before closing (Aviato will not auto-close)."
            )
            return SettingsDriftOutcome(status="resolved")
        return SettingsDriftOutcome(status="clean")

    current_id = diff_identity(diff) if diff.changes else None
    consent_voided = False
    # Consent voiding is tied to the SETTINGS diff only (rulesets carry no consent). Skip when
    # there is no settings diff to compare against.
    if diff.changes and issue is not None and issue.consent_diff_id is not None and issue.consent_diff_id != current_id:
        # The reported diff changed since consent was granted: VOID the prior consent by
        # removing its grant record, not merely commenting (§5.6:633/§6.4). A comment alone
        # would leave the old grant label in place, so if drift later oscillates BACK to the
        # old diff id the stale label would re-authorize without fresh human consent. Revoke
        # first (it fails loud on a real error), then comment. The §5.7 apply-time recompute
        # remains the authoritative gate; this closes the oscillation gap at report time.
        platform.revoke_consent(repo, issue_key, issue.consent_diff_id)
        platform.comment_issue(
            repo,
            issue_key,
            "Reported diff changed since consent was granted; the prior consent has been voided "
            "(re-consent on the current diff to proceed).",
        )
        consent_voided = True

    platform.open_or_update_issue(
        repo, issue_key, "Aviato: settings drift", _render_issue_body(diff, missing_rulesets, repo, issue_key)
    )
    return SettingsDriftOutcome(
        status="reported",
        destructive=diff.destructive,
        consent_voided=consent_voided,
        diff_id=current_id,
        missing_rulesets=tuple(sorted(missing_rulesets)),
    )
