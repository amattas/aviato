from __future__ import annotations

from typing import Any

from aviato.core.ports import Issue


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
        issues: dict[str, Issue] | None = None,
        issues_disabled: bool = False,
        fail_full_protection: bool = False,
        fail_apply: bool = False,
        fail_comment: bool = False,
    ) -> None:
        self.settings = settings or {}
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
        self.calls: list[tuple[str, tuple]] = []

    def read_settings(self, repo: str) -> dict[str, Any]:
        return dict(self.settings)

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

    def open_or_update_proposal(self, repo: str, branch: str, title: str, files: dict[str, str], body: str) -> str:
        self.calls.append(("open_or_update_proposal", (repo, branch, title, files, body)))
        return branch

    def apply_settings(self, repo: str, payload: dict[str, Any]) -> None:
        self._apply_count += 1
        if self.fail_apply:
            raise RuntimeError("settings apply rejected by platform")
        if self.fail_full_protection and self._apply_count >= 2:
            raise RuntimeError("full protection rejected by platform")
        self.calls.append(("apply_settings", (repo, payload)))
        self.settings.update(payload)

    def create_repo(self, repo: str, *, private: bool) -> None:
        self.calls.append(("create_repo", (repo, private)))

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]
