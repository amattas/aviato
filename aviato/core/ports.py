from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class GitObjectType(StrEnum):
    """Validated Git object kinds returned by GitHub's ref/object endpoints."""

    COMMIT = "commit"
    TAG = "tag"


class GitObjectReadStatus(StrEnum):
    """The fail-closed semantic result of reading one Git object endpoint."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"


@dataclass(frozen=True)
class RepositoryIdentity:
    """The immutable identity positively read for one accessible GitHub repository."""

    database_id: int
    node_id: str
    full_name: str
    default_branch: str


@dataclass(frozen=True)
class GitObjectRead:
    """A typed Git-object read that cannot collapse an error into absence."""

    status: GitObjectReadStatus
    endpoint: str
    object_type: GitObjectType | None = None
    sha: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status is GitObjectReadStatus.FOUND:
            if self.object_type is None or self.sha is None or self.error is not None:
                raise ValueError("a FOUND Git object read requires type and SHA, without an error")
            return
        if self.object_type is not None or self.sha is not None:
            raise ValueError("a non-FOUND Git object read cannot contain object data")
        if self.status is GitObjectReadStatus.ERROR and not self.error:
            raise ValueError("an ERROR Git object read requires an error")
        if self.status is GitObjectReadStatus.NOT_FOUND and self.error is not None:
            raise ValueError("a NOT_FOUND Git object read cannot contain an error")


class LibraryRefKind(StrEnum):
    """The authoritative ref namespace selected for a Library pin."""

    TAG = "tag"
    BRANCH = "branch"


@dataclass(frozen=True)
class ResolvedLibraryRef:
    """One Library pin bound to an exact repository and peeled commit."""

    repository_identity: RepositoryIdentity
    ref_kind: LibraryRefKind
    requested_pin: str
    object_sha: str
    commit_sha: str


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
    # R2-5: more than one OPEN tracking issue shares this key — consent is ambiguous (a grant on
    # one duplicate, a revoke on another), so reconcile must refuse until they're de-duplicated.
    ambiguous: bool = False


@dataclass(frozen=True)
class RulesetApplyResult:
    """Outcome of one ruleset upsert, including any unsupported rules omitted."""

    message: str
    degraded_rules: tuple[str, ...] = ()


@runtime_checkable
class Platform(Protocol):
    """The §2.14 hosting-platform binding interface.

    The core depends only on this Protocol; the concrete GitHub binding lives
    outside the agnostic core (it is the day-zero binding). Read/propose/report
    methods are low-privilege; ``apply_settings`` is the only mutating call and is
    reached only through the §5.7 gated path.
    """

    def read_settings(self, repo: str) -> dict[str, Any]: ...

    def read_rulesets(self, repo: str) -> list[dict[str, Any]]: ...

    def get_issue(self, repo: str, key: str) -> Issue | None: ...

    def open_or_update_issue(self, repo: str, key: str, title: str, body: str) -> str: ...

    def comment_issue(self, repo: str, key: str, body: str) -> None: ...

    def revoke_consent(self, repo: str, key: str, diff_id: str) -> None: ...

    def open_or_update_proposal(self, repo: str, branch: str, title: str, files: dict[str, str], body: str) -> str: ...

    def apply_settings(
        self, repo: str, payload: dict[str, Any], *, expected_live: dict[str, Any] | None = None
    ) -> list[str]:
        """Apply the desired settings; return the names of any desired toggles that were SKIPPED.

        R5-4: a §17 security toggle (e.g. secret scanning) can be unavailable on the repo, in which
        case it is surfaced-and-skipped rather than failing the whole apply (the safety-critical
        branch protection still lands). The skipped keys are returned so the §5.7 audit does not
        overstate a clean apply. An empty list means everything in the desired set was applied.
        """
        ...

    def create_repo(self, repo: str, *, private: bool) -> None: ...
