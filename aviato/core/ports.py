from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Issue:
    """A tracking issue as seen by the core (§5.6/§5.7), free of platform specifics."""

    key: str
    open: bool
    consent_diff_id: str | None = None
    consent_actor_type: str | None = None
    consent_role: str | None = None
    consent_role_lookup_ok: bool = False
    edited_by_nonhuman_since_grant: bool = False


@runtime_checkable
class Platform(Protocol):
    """The §2.14 hosting-platform binding interface.

    The core depends only on this Protocol; the concrete GitHub binding lives
    outside the agnostic core (it is the day-zero binding). Read/propose/report
    methods are low-privilege; ``apply_settings`` is the only mutating call and is
    reached only through the §5.7 gated path.
    """

    def read_settings(self, repo: str) -> dict[str, Any]: ...

    def get_issue(self, repo: str, key: str) -> Issue | None: ...

    def open_or_update_issue(self, repo: str, key: str, title: str, body: str) -> str: ...

    def comment_issue(self, repo: str, key: str, body: str) -> None: ...

    def open_or_update_proposal(self, repo: str, branch: str, title: str, files: dict[str, str], body: str) -> str: ...

    def apply_settings(self, repo: str, payload: dict[str, Any]) -> None: ...
