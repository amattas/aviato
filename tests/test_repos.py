from __future__ import annotations

import pytest

from aviato.repos import is_owner_repo_slug, normalize_slug


def test_normalize_slug_from_https_remote() -> None:
    assert normalize_slug("https://github.com/amattas/aviato.git") == "amattas/aviato"


def test_normalize_slug_from_ssh_remote() -> None:
    assert normalize_slug("git@github.com:amattas/aviato.git") == "amattas/aviato"


def test_dot_leading_repository_segment_is_a_valid_github_slug() -> None:
    assert is_owner_repo_slug("github/.github") is True
    assert normalize_slug("https://github.com/github/.github.git") == "github/.github"
    assert normalize_slug("git@github.com:github/.github.git") == "github/.github"


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "owner",
        "owner/repo/extra",
        "owner//repo",
        ".owner/repo",
        "-owner/repo",
        "_owner/repo",
        "owner/.",
        "owner/..",
        "owner/../repo",
        "owner/repo?query",
        "owner/repo#fragment",
    ],
)
def test_owner_repo_slug_rejects_unsafe_or_ambiguous_shapes(slug: str) -> None:
    assert is_owner_repo_slug(slug) is False


def test_normalize_slug_requires_exact_github_host_and_clean_owner_repo() -> None:
    # R2-8/§2.14: exact host match + clean owner/repo, so a look-alike host or a path-/query-shaped
    # segment can't slip through and later corrupt an API endpoint.
    from aviato.repos import normalize_slug

    assert normalize_slug("https://github.com/amattas/aviato.git") == "amattas/aviato"
    assert normalize_slug("git@github.com:amattas/aviato.git") == "amattas/aviato"
    assert normalize_slug("ssh://git@github.com/amattas/aviato") == "amattas/aviato"
    # Look-alike hosts are rejected.
    assert normalize_slug("https://notgithub.com/o/r.git") == ""
    assert normalize_slug("https://github.com.evil.com/o/r") == ""
    # Sub-paths and scp-style query-shaped repos are rejected.
    assert normalize_slug("https://github.com/o/r/extra") == ""
    assert normalize_slug("git@github.com:o/r?x") == ""
