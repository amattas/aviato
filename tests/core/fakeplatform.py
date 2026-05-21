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
    ) -> None:
        self.settings = settings or {}
        self.issues = issues or {}
        self.issues_disabled = issues_disabled
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
        if self.issues_disabled:
            raise RuntimeError("issue channel unavailable")
        self.calls.append(("comment_issue", (repo, key, body)))

    def open_or_update_proposal(self, repo: str, branch: str, title: str, files: dict[str, str], body: str) -> str:
        self.calls.append(("open_or_update_proposal", (repo, branch, title, files, body)))
        return branch

    def apply_settings(self, repo: str, payload: dict[str, Any]) -> None:
        self.calls.append(("apply_settings", (repo, payload)))
        self.settings.update(payload)

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]
