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
    # Desired rulesets MISSING from, or content-DRIFTED on, the live platform (§5.6). Report-only
    # and remediated by `apply-rulesets` (NOT the consent-gated §5.7 reconcile, which only writes
    # branch/security). The caller (CLI/binding) computes these — the core flow stays agnostic of
    # GitHub ruleset shape and just reports the names.
    drifted_rulesets: tuple[str, ...] = ()


def _render_change(diff: SettingsDiff, key: str) -> str:
    kind = diff.changes[key]
    vals = diff.values.get(key, {})
    return f"- {key}: {kind} ({vals.get('live')!r} -> {vals.get('desired')!r})"


def _render_issue_body(
    diff: SettingsDiff,
    drifted_rulesets: list[str],
    repo: str,
    issue_key: str,
    profile: str | None,
    declaration_path: str | None = None,
) -> str:
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
    if drifted_rulesets:
        # Rulesets are remediated by the operator-direct, idempotent `apply-rulesets` (which
        # re-asserts the rendered desired content), NOT the §5.7 reconcile (branch/security only).
        # Reported here so a missing OR content-weakened (disabled / permissive pattern / lowered
        # approvals) required ruleset is not invisible (§5.6). C12-3: prefer `--declaration <path>`
        # so the restored ruleset resolves the consumer's OVERRIDES (the SAME status checks drift
        # used) and never re-adds a check the consumer removed; fall back to `--profile` (base) only
        # when no declaration path is known.
        if declaration_path:
            apply_flag = f" --declaration {declaration_path}"
        elif profile:
            apply_flag = f" --profile {profile}"
        else:
            apply_flag = ""
        lines += [
            "",
            "Missing or drifted required rulesets (apply separately — NOT via reconcile):",
        ]
        lines += [f"- {name}" for name in sorted(drifted_rulesets)]
        lines += [
            "",
            f"To restore them, an operator runs:    aviato apply-rulesets {repo} --apply{apply_flag}",
        ]
    lines += ["", "No settings mutation has been performed (report-only, §5.6)."]
    return "\n".join(lines)


def run_settings_drift(
    platform: Platform,
    *,
    repo: str,
    desired_settings: dict[str, Any],
    issue_key: str,
    drifted_rulesets: tuple[str, ...] = (),
    profile: str | None = None,
    declaration_path: str | None = None,
) -> SettingsDriftOutcome:
    """Report (never apply) settings drift (§5.6).

    Reads live settings, classifies the diff (additive/destructive, ambiguous =
    destructive), and on a non-empty diff opens/updates the tracking issue with
    the diff and the operator reconcile command. An empty diff comments "resolved
    — verify before closing" on an open issue (never auto-closes). If a prior
    consent record no longer matches the current diff (changed OR resolved), it is
    voided (label removed), so a later reappearance needs fresh consent (§8.3).

    Also reports **missing or content-drifted required rulesets** (§5.6): the caller
    passes ``drifted_rulesets`` (computed from the rendered desired vs the live payloads —
    the GitHub-specific comparison lives outside this agnostic flow), surfaced on the same
    tracking issue and remediated by ``apply-rulesets --apply --profile`` (NOT the
    consent-gated reconcile, which writes only branch/security).

    The issue channel being unavailable fails loud (the platform raises); an
    unreadable settings surface fails closed as SettingsReadError. No settings
    mutation is ever performed.
    """
    live = platform.read_settings(repo)
    diff = classify_settings(desired=desired_settings, live=live)
    issue = platform.get_issue(repo, issue_key)

    current_id = diff_identity(diff) if diff.changes else None
    # §5.6:633/§6.4/§8.3: VOID any prior consent that no longer matches the current SETTINGS diff
    # — whether the diff CHANGED to a different id OR RESOLVED to empty (current_id is None). A
    # comment alone would leave the grant label in place, so a later reappearance of the old diff
    # (incl. an A→∅→A oscillation) would re-authorize without fresh human consent. Removing the
    # label is the actual void; §5.7 apply-time recompute remains the authoritative gate. Rulesets
    # carry no consent, so this is settings-only. Computed BEFORE the resolved branch so a
    # resolved-to-empty diff also voids its stale consent.
    consent_voided = False
    if issue is not None and issue.consent_diff_id is not None and issue.consent_diff_id != current_id:
        consent_voided = True
        platform.revoke_consent(repo, issue_key, issue.consent_diff_id)

    if not diff.changes and not drifted_rulesets:
        if issue is not None and issue.open:
            note = " The prior consent has been voided (re-consent on a new diff)." if consent_voided else ""
            platform.comment_issue(
                repo,
                issue_key,
                f"Drift resolved — verify before closing (Aviato will not auto-close).{note}",
            )
            return SettingsDriftOutcome(status="resolved", consent_voided=consent_voided)
        return SettingsDriftOutcome(status="clean", consent_voided=consent_voided)

    if consent_voided:
        platform.comment_issue(
            repo,
            issue_key,
            "Reported settings diff changed (or resolved) since consent was granted; the prior "
            "consent has been voided (re-consent on the current diff to proceed).",
        )

    platform.open_or_update_issue(
        repo,
        issue_key,
        "Aviato: settings drift",
        _render_issue_body(diff, list(drifted_rulesets), repo, issue_key, profile, declaration_path),
    )
    return SettingsDriftOutcome(
        status="reported",
        destructive=diff.destructive,
        consent_voided=consent_voided,
        diff_id=current_id,
        drifted_rulesets=tuple(sorted(drifted_rulesets)),
    )
