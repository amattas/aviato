from __future__ import annotations

from aviato.repos import normalize_slug


def test_normalize_slug_from_https_remote() -> None:
    assert normalize_slug("https://github.com/amattas/aviato.git") == "amattas/aviato"


def test_normalize_slug_from_ssh_remote() -> None:
    assert normalize_slug("git@github.com:amattas/aviato.git") == "amattas/aviato"


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
