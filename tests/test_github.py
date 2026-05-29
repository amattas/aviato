from __future__ import annotations

import subprocess

import pytest

from aviato import github


def test_gh_json_raises_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 1, "", "authentication failed")

    monkeypatch.setattr(github, "run", fake_run)

    with pytest.raises(github.GitHubAPIError):
        github.gh_json("repos/amattas/aviato")


def test_gh_json_can_allow_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 1, "", "not found")

    monkeypatch.setattr(github, "run", fake_run)

    assert github.gh_json("repos/amattas/aviato/rulesets", default=[], allow_error=True) == []


def test_gh_json_optional_raises_on_non_404_containing_not_found_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 403/auth/5xx whose stderr merely CONTAINS "not found"/"no such" must RAISE, not be
    # read as an empty 404 — keying off the bare phrase re-opens the §2.7 fail-OPEN read
    # (a falsely-"unprotected"/"no-issue" state). Only the HTTP 404 status is a genuine 404.
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 1, "", "gh: Resource not found or no such host (HTTP 403)")

    monkeypatch.setattr(github, "run", fake_run)
    with pytest.raises(github.GitHubAPIError):
        github.gh_json_optional("repos/o/r/branches/main/protection", default={})


def test_gh_json_optional_returns_default_on_genuine_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 1, "", "gh: Not Found (HTTP 404)")

    monkeypatch.setattr(github, "run", fake_run)
    assert github.gh_json_optional("repos/o/r/branches/main/protection", default={}) == {}


def test_upsert_ruleset_posts_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [])
    calls: list[list[str]] = []
    monkeypatch.setattr(
        github, "run", lambda cmd, **__: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    )
    result = github.upsert_ruleset("o/r", {"name": "Common: protect default branch"}, apply=True)
    assert "Created" in result
    method = calls[0][calls[0].index("--method") + 1]
    assert method == "POST"
    assert "repos/o/r/rulesets" in calls[0]


def test_upsert_ruleset_puts_to_existing_id_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        github,
        "repository_rulesets",
        lambda slug: [{"name": "Common: protect default branch", "id": 4242}],
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        github, "run", lambda cmd, **__: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    )
    result = github.upsert_ruleset("o/r", {"name": "Common: protect default branch"}, apply=True)
    assert "Updated" in result
    method = calls[0][calls[0].index("--method") + 1]
    assert method == "PUT"
    assert "repos/o/r/rulesets/4242" in calls[0]


def test_upsert_ruleset_dry_run_does_not_mutate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [])
    monkeypatch.setattr(
        github, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call gh on dry run"))
    )
    msg = github.upsert_ruleset("o/r", {"name": "X"}, apply=False)
    assert msg.startswith("DRY RUN")


def test_upsert_ruleset_requires_name(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        github.upsert_ruleset("o/r", {}, apply=True)


def test_repository_rulesets_follows_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    # A repo with more rulesets than one page must not hide an existing ruleset on a
    # later page — otherwise upsert would POST a duplicate instead of PUT-updating.
    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert "--paginate" in cmd and "--slurp" in cmd, "rulesets list must be paginated"
        body = '[[{"name": "other", "id": 1}], [{"name": "Common: protect default branch", "id": 99}]]'
        return subprocess.CompletedProcess(cmd, 0, body, "")

    monkeypatch.setattr(github, "run", fake_run)
    names = [r["name"] for r in github.repository_rulesets("o/r")]
    assert "Common: protect default branch" in names


def test_settings_read_token_scope_overrides_then_restores_gh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    # §5.6/§11.2: inside the scope gh reads use the admin READ token; afterwards GH_TOKEN is
    # restored so the issue WRITES run under the ambient platform token (the admin token mutates
    # nothing — it is read-only in use).
    monkeypatch.setenv("GH_TOKEN", "platform-token")
    monkeypatch.setenv(github.SETTINGS_READ_TOKEN_ENV, "admin-read-token")
    with github.settings_read_token_scope():
        assert os.environ["GH_TOKEN"] == "admin-read-token"
    assert os.environ["GH_TOKEN"] == "platform-token"


def test_settings_read_token_scope_is_noop_without_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.setenv("GH_TOKEN", "platform-token")
    monkeypatch.delenv(github.SETTINGS_READ_TOKEN_ENV, raising=False)
    with github.settings_read_token_scope():
        assert os.environ["GH_TOKEN"] == "platform-token"  # unchanged
    assert os.environ["GH_TOKEN"] == "platform-token"


def test_pages_source_is_actions_returns_none_on_404_or_missing_schema(monkeypatch) -> None:
    # R7-3-PAGES-§5.14: a 404 from /pages conflates "off" with "no perms" and "invisible" — the
    # honest mapping is unknown (None), per §5.14 "absence/unreadable reads as broken, not clean".
    # R7-3-PAGES-SCHEMA: a present dict lacking build_type (schema drift) is also unknown, not no.
    from aviato import github as gh

    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: None)  # the 404 path
    assert gh.pages_source_is_actions("o/r") is None
    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: "weird-non-dict")
    assert gh.pages_source_is_actions("o/r") is None
    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: {"public": True})  # no build_type
    assert gh.pages_source_is_actions("o/r") is None


def test_pages_source_is_actions_resolves_workflow_vs_legacy(monkeypatch) -> None:
    # The two determinate cases the API DOES distinguish: Actions-sourced (workflow) vs branch.
    from aviato import github as gh

    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: {"build_type": "workflow"})
    assert gh.pages_source_is_actions("o/r") is True
    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: {"build_type": "legacy"})
    assert gh.pages_source_is_actions("o/r") is False
