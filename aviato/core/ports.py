from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

_REPOSITORY_SLUG_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/(?:[A-Za-z0-9][A-Za-z0-9._-]*|\.[A-Za-z0-9_-][A-Za-z0-9._-]*)$"
)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GIT_OBJECT_ENDPOINT_RE = re.compile(
    r"^repos/[A-Za-z0-9][A-Za-z0-9._-]*/"
    r"(?:[A-Za-z0-9][A-Za-z0-9._-]*|\.[A-Za-z0-9_-][A-Za-z0-9._-]*)/git/"
    r"(?:ref/(?:heads|tags)/[^/?#\\\s]+|tags/[0-9a-f]{40})$"
)


def _is_repository_slug(value: str) -> bool:
    if _REPOSITORY_SLUG_RE.fullmatch(value) is None:
        return False
    repository = value.partition("/")[2]
    return repository not in {".", ".."}


def validate_git_ref_name(name: str) -> None:
    """Validate one branch/tag name using Git ref-format and branch safety rules."""

    invalid = (
        not isinstance(name, str)
        or not name
        or name.endswith(".")
        or ".." in name
        or "@{" in name
    )
    components = name.split("/") if isinstance(name, str) else []
    invalid = invalid or any(
        not component or component.startswith(".") or component.endswith(".lock") for component in components
    )
    invalid = invalid or any(
        ord(character) <= 0x20 or ord(character) == 0x7F or character in "~^:?*[\\" for character in name
    )
    if invalid:
        raise ValueError(f"invalid Git ref name: {name!r}")


class GitObjectType(StrEnum):
    """Validated Git object kinds returned by GitHub's ref/object endpoints."""

    COMMIT = "commit"
    TAG = "tag"


class GitObjectReadStatus(StrEnum):
    """The fail-closed semantic result of reading one Git object endpoint."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"


class GitRefNamespace(StrEnum):
    """GitHub ref namespaces that may resolve a Library pin."""

    HEADS = "heads"
    TAGS = "tags"


@dataclass(frozen=True)
class RepositoryIdentity:
    """The immutable identity positively read for one accessible GitHub repository."""

    database_id: int
    node_id: str
    full_name: str
    default_branch: str

    def __post_init__(self) -> None:
        if isinstance(self.database_id, bool) or not isinstance(self.database_id, int) or self.database_id <= 0:
            raise ValueError("repository database_id must be a positive integer")
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("repository node_id must be a nonempty string")
        if not isinstance(self.full_name, str) or not _is_repository_slug(self.full_name):
            raise ValueError("repository full_name must be a canonical owner/repo slug")
        try:
            validate_git_ref_name(self.default_branch)
        except ValueError as exc:
            raise ValueError("repository default_branch must be a valid Git ref name") from exc


@dataclass(frozen=True)
class GitObjectRead:
    """A typed Git-object read that cannot collapse an error into absence."""

    status: GitObjectReadStatus
    endpoint: str
    object_type: GitObjectType | None = None
    sha: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GitObjectReadStatus):
            raise ValueError("Git object read status must be a GitObjectReadStatus")
        if not isinstance(self.endpoint, str) or _GIT_OBJECT_ENDPOINT_RE.fullmatch(self.endpoint) is None:
            raise ValueError("Git object read endpoint must be a canonical repository Git-object endpoint")
        if self.status is GitObjectReadStatus.FOUND:
            if (
                not isinstance(self.object_type, GitObjectType)
                or not isinstance(self.sha, str)
                or _GIT_SHA_RE.fullmatch(self.sha) is None
                or self.error is not None
            ):
                raise ValueError("a FOUND Git object read requires type and SHA, without an error")
            return
        if self.object_type is not None or self.sha is not None:
            raise ValueError("a non-FOUND Git object read cannot contain object data")
        if self.status is GitObjectReadStatus.ERROR and (not isinstance(self.error, str) or not self.error.strip()):
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

    def __post_init__(self) -> None:
        if not isinstance(self.repository_identity, RepositoryIdentity):
            raise ValueError("resolved Library ref requires a RepositoryIdentity")
        if not isinstance(self.ref_kind, LibraryRefKind):
            raise ValueError("resolved Library ref kind must be a LibraryRefKind")
        try:
            validate_git_ref_name(self.requested_pin)
        except ValueError as exc:
            raise ValueError("resolved Library ref requested_pin must be a valid Git ref name") from exc
        if not isinstance(self.object_sha, str) or _GIT_SHA_RE.fullmatch(self.object_sha) is None:
            raise ValueError("resolved Library ref object_sha must be a lowercase 40-hex SHA")
        if not isinstance(self.commit_sha, str) or _GIT_SHA_RE.fullmatch(self.commit_sha) is None:
            raise ValueError("resolved Library ref commit_sha must be a lowercase 40-hex SHA")
        if self.ref_kind is LibraryRefKind.BRANCH and self.object_sha != self.commit_sha:
            raise ValueError("a resolved branch object SHA must equal its commit SHA")


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
