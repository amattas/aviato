"""The in-memory test double must satisfy the §2.14 Platform port.

Core-flow tests run against FakePlatform; if its surface drifts from the protocol the
real binding implements, those tests would pass against a shape GitHubPlatform doesn't
have. The isinstance assert (Platform is @runtime_checkable) pins the two together.
"""

from typing import Any

import pytest

from aviato.core.ports import (
    GitObjectRead,
    GitObjectReadStatus,
    GitObjectType,
    LibraryRefKind,
    Platform,
    RepositoryIdentity,
    ResolvedLibraryRef,
)

from .fakeplatform import FakePlatform


def test_fakeplatform_satisfies_platform_protocol() -> None:
    assert isinstance(FakePlatform(), Platform)


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_id": 0},
        {"database_id": True},
        {"node_id": ""},
        {"full_name": "owner-only"},
        {"full_name": "owner//repo"},
        {"default_branch": ""},
        {"default_branch": "bad?query"},
    ],
)
def test_repository_identity_rejects_invalid_runtime_fields(overrides: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "database_id": 17,
        "node_id": "R_test",
        "full_name": "owner/repo",
        "default_branch": "main",
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        RepositoryIdentity(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "found"},
        {"endpoint": ""},
        {"endpoint": "https://api.github.test/repos/owner/repo"},
        {"object_type": "commit"},
        {"sha": "a" * 39},
        {"sha": "A" * 40},
    ],
)
def test_git_object_read_rejects_invalid_runtime_fields(overrides: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "status": GitObjectReadStatus.FOUND,
        "endpoint": "repos/owner/repo/git/ref/heads/main",
        "object_type": GitObjectType.COMMIT,
        "sha": "a" * 40,
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        GitObjectRead(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository_identity": "owner/repo"},
        {"ref_kind": "branch"},
        {"requested_pin": ""},
        {"requested_pin": "bad?query"},
        {"object_sha": "a" * 39},
        {"commit_sha": "A" * 40},
        {"object_sha": "a" * 40, "commit_sha": "b" * 40},
    ],
)
def test_resolved_library_ref_rejects_invalid_runtime_fields(overrides: dict[str, Any]) -> None:
    identity = RepositoryIdentity(17, "R_test", "owner/repo", "main")
    values: dict[str, Any] = {
        "repository_identity": identity,
        "ref_kind": LibraryRefKind.BRANCH,
        "requested_pin": "main",
        "object_sha": "a" * 40,
        "commit_sha": "a" * 40,
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        ResolvedLibraryRef(**values)
