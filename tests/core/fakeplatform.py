from __future__ import annotations

import dataclasses
from typing import Any

from aviato.core.ports import Issue, Platform, SettingsApplyResult


class FakePlatform:
    """In-memory :class:`aviato.core.ports.Platform` for testing orchestration flows.

    Records mutating/reporting calls so tests can assert behavior without a live
    hosting platform. ``issues_disabled`` simulates an unavailable issue channel
    (§5.6 fail-loud).
    """

    def __init__(
        self,
        *,
        settings: dict[str, Any] | None = None,
        rulesets: list[dict[str, Any]] | None = None,
        issues: dict[str, Issue] | None = None,
        issues_disabled: bool = False,
        fail_full_protection: bool = False,
        fail_apply: bool = False,
        fail_comment: bool = False,
    ) -> None:
        self.settings = settings or {}
        self.rulesets = rulesets if rulesets is not None else []
        self.issues = issues or {}
        self.issues_disabled = issues_disabled
        # When set, comment_issue raises (but reads/applies still work) — simulates a transient
        # failure posting the §5.7 audit breadcrumb after the privileged apply already landed.
        self.fail_comment = fail_comment
        # When set, the SECOND apply_settings (full protection) raises — simulating the
        # §8.7 partially-provisioned state for provision-flow tests.
        self.fail_full_protection = fail_full_protection
        # When set, the FIRST apply_settings raises — simulates a settings apply that throws
        # mid-flight (§5.7 audit-trail test).
        self.fail_apply = fail_apply
        self._apply_count = 0
        # R5-4: desired security toggles apply_settings should report as SKIPPED (feature
        # unavailable). These are the real platform-API toggle names (to_security_payload shape),
        # NOT desired-key-shaped stand-ins. Empty by default → a clean, full apply.
        self.skipped_on_apply: list[str] = []
        # §5.7: free-text NOTES about extra mutations the apply performed outside the diff (e.g. a
        # cleared conflicting classic PR-review block). A distinct channel from ``skipped_on_apply``.
        self.notes_on_apply: list[str] = []
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def read_settings(self, repo: str) -> dict[str, Any]:
        return dict(self.settings)

    def read_rulesets(self, repo: str) -> list[dict[str, Any]]:
        return list(self.rulesets)

    def get_issue(self, repo: str, key: str) -> Issue | None:
        return self.issues.get(key)

    def open_or_update_issue(self, repo: str, key: str, title: str, body: str) -> str:
        if self.issues_disabled:
            raise RuntimeError("issue channel unavailable")
        self.calls.append(("open_or_update_issue", (repo, key, title, body)))
        return key

    def comment_issue(self, repo: str, key: str, body: str) -> None:
        if self.issues_disabled or self.fail_comment:
            raise RuntimeError("issue channel unavailable")
        self.calls.append(("comment_issue", (repo, key, body)))

    def revoke_consent(self, repo: str, key: str, diff_id: str) -> None:
        if self.issues_disabled:
            raise RuntimeError("issue channel unavailable")
        self.calls.append(("revoke_consent", (repo, key, diff_id)))
        # Reflect the void in the in-memory issue so a later get_issue sees no stale consent
        # (the §8.3 oscillation guard the real binding enforces by removing the label).
        issue = self.issues.get(key)
        if issue is not None and issue.consent_diff_id == diff_id:
            self.issues[key] = dataclasses.replace(
                issue,
                consent_diff_id=None,
                consent_actor_type=None,
                consent_role=None,
                consent_role_lookup_ok=False,
            )

    def open_or_update_proposal(self, repo: str, branch: str, title: str, files: dict[str, str], body: str) -> str:
        self.calls.append(("open_or_update_proposal", (repo, branch, title, files, body)))
        return branch

    def apply_settings(
        self, repo: str, payload: dict[str, Any], *, expected_live: dict[str, Any] | None = None
    ) -> SettingsApplyResult:
        self._apply_count += 1
        if self.fail_apply:
            raise RuntimeError("settings apply rejected by platform")
        if self.fail_full_protection and self._apply_count >= 2:
            raise RuntimeError("full protection rejected by platform")
        self.calls.append(("apply_settings", (repo, payload, expected_live)))
        self.settings.update(payload)
        # R5-4: simulate a §17 toggle surfaced-and-skipped (feature unavailable) and/or a mutation
        # note, in their SEPARATE channels, so flow tests assert the audit labels each correctly.
        # Default: full apply, no extras.
        return SettingsApplyResult(skipped=tuple(self.skipped_on_apply), notes=tuple(self.notes_on_apply))

    def create_repo(self, repo: str, *, private: bool) -> None:
        self.calls.append(("create_repo", (repo, private)))

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


_platform_contract: Platform = FakePlatform()
