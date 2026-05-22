from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aviato import github
from aviato.core.ports import Platform
from aviato.github_platform import (
    GitHubPlatform,
    UnmodeledProtectionError,
    _label_events,
    current_consent,
    map_branch_settings,
    nonhuman_edit_after_grant,
    to_branch_protection_payload,
)


def test_apply_settings_fails_closed_on_unmodeled_protection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(github, "active_branch_rules", lambda repo, branch: [])
    monkeypatch.setattr(
        github,
        "classic_branch_protection",
        lambda repo, branch: {"restrictions": {"users": ["alice"]}},  # unmodeled push restriction
    )
    monkeypatch.setattr(github, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not PUT")))
    with pytest.raises(UnmodeledProtectionError):
        GitHubPlatform().apply_settings("o/r", {"requires_pull_request": True})


def test_apply_settings_fails_closed_on_unmodeled_ruleset_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    # A branch RULESET carrying a rule the desired model doesn't represent must also
    # fail closed — the classic PUT would leave a dual-control state the operator
    # never reviewed (§2.4/§5.7), not just classic push restrictions.
    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(github, "classic_branch_protection", lambda repo, branch: {})
    monkeypatch.setattr(
        github,
        "active_branch_rules",
        lambda repo, branch: [{"type": "commit_message_pattern", "parameters": {}}],
    )
    monkeypatch.setattr(github, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not PUT")))
    with pytest.raises(UnmodeledProtectionError):
        GitHubPlatform().apply_settings("o/r", {"requires_pull_request": True})


def test_apply_settings_puts_classic_protection_when_no_ruleset_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    # No branch rules → protection is on the classic surface, so the classic PUT is the
    # correct (only) surface to write.
    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(github, "classic_branch_protection", lambda repo, branch: {})
    monkeypatch.setattr(github, "active_branch_rules", lambda repo, branch: [])
    calls: list[list[str]] = []
    monkeypatch.setattr(
        github, "run", lambda cmd, **__: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    )
    GitHubPlatform().apply_settings("o/r", {"requires_pull_request": True, "required_reviews": 1})
    assert any("PUT" in c and "protection" in " ".join(c) for c in calls)


def test_apply_settings_fails_closed_when_ruleset_owns_protection_and_desired_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Branch protection is enforced by a RULESET (the bundled protect-default-branch),
    # which this settings reconcile cannot write — it can only PUT classic protection.
    # If the desired branch-protection state differs from what the ruleset enforces,
    # writing classic protection would create an unreviewed dual-control divergence and
    # could silently fail to apply a relaxation. Fail closed instead of reporting applied.
    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(github, "classic_branch_protection", lambda repo, branch: {})
    monkeypatch.setattr(
        github,
        "active_branch_rules",
        lambda repo, branch: [{"type": "pull_request", "parameters": {"required_approving_review_count": 1}}],
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        github, "run", lambda cmd, **__: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    )
    with pytest.raises(UnmodeledProtectionError):
        GitHubPlatform().apply_settings("o/r", {"requires_pull_request": True, "required_reviews": 2})
    assert not any("PUT" in c for c in calls), "must not write the wrong (classic) surface"


def test_apply_settings_skips_classic_put_when_ruleset_already_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    # The ruleset already enforces the desired branch protection → nothing to write on
    # that surface (no false classic PUT), but the security toggles (a DIFFERENT surface)
    # still reconcile.
    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(github, "classic_branch_protection", lambda repo, branch: {})
    monkeypatch.setattr(github, "active_branch_rules", lambda repo, branch: [{"type": "pull_request"}])
    calls: list[list[str]] = []
    monkeypatch.setattr(
        github, "run", lambda cmd, **__: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    )
    GitHubPlatform().apply_settings("o/r", {"requires_pull_request": True, "secret_scanning": True})
    assert not any("protection" in " ".join(c) for c in calls), "must not PUT classic protection"
    assert any("PATCH" in c for c in calls), "security toggle (separate surface) must still apply"


def test_apply_settings_tolerates_unavailable_security_feature(monkeypatch: pytest.MonkeyPatch) -> None:
    # §17: a security feature unavailable on the repo (e.g. secret scanning on a private
    # repo without Advanced Security) is an adoption warning, not an apply failure — the
    # branch-protection PUT still applies. Live-test regression (provision smoke).
    from aviato.command import CommandError

    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(github, "classic_branch_protection", lambda repo, branch: {})

    def fake_run(cmd, **__):
        if "PATCH" in cmd:  # the security_and_analysis toggle
            raise CommandError(cmd, 1, "gh: Secret scanning is not available for this repository. (HTTP 422)")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(github, "run", fake_run)
    # Must NOT raise despite the security PATCH failing as unavailable.
    GitHubPlatform().apply_settings("o/r", {"requires_pull_request": True, "secret_scanning": True})


def test_apply_settings_reraises_non_feature_security_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from aviato.command import CommandError

    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(github, "classic_branch_protection", lambda repo, branch: {})

    def fake_run(cmd, **__):
        if "PATCH" in cmd:
            raise CommandError(cmd, 1, "gh: Server Error (HTTP 500)")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(github, "run", fake_run)
    with pytest.raises(CommandError):
        GitHubPlatform().apply_settings("o/r", {"requires_pull_request": True, "secret_scanning": True})


def test_nonhuman_edit_after_grant_detects_bot() -> None:
    timeline = [
        {"event": "labeled", "label": {"name": "aviato-consent:abc"}, "actor": {"type": "User"}},
        {"event": "commented", "actor": {"type": "Bot"}},
    ]
    assert nonhuman_edit_after_grant(timeline, "abc") is True


def test_nonhuman_edit_after_grant_false_when_only_humans_after() -> None:
    timeline = [
        {"event": "labeled", "label": {"name": "aviato-consent:abc"}, "actor": {"type": "User"}},
        {"event": "commented", "actor": {"type": "User"}},
        {"event": "renamed"},  # actorless system event ignored
    ]
    assert nonhuman_edit_after_grant(timeline, "abc") is False


def test_nonhuman_edit_unknown_actor_type_fails_closed() -> None:
    timeline = [
        {"event": "labeled", "label": {"name": "aviato-consent:abc"}, "actor": {"type": "User"}},
        {"event": "commented", "actor": {"login": "x"}},  # actor present, type unknown → fail closed
    ]
    assert nonhuman_edit_after_grant(timeline, "abc") is True


def test_nonhuman_edit_before_grant_does_not_count() -> None:
    timeline = [
        {"event": "commented", "actor": {"type": "Bot"}},
        {"event": "labeled", "label": {"name": "aviato-consent:abc"}, "actor": {"type": "User"}},
    ]
    assert nonhuman_edit_after_grant(timeline, "abc") is False


def test_current_consent_returns_active_grant() -> None:
    events = [{"action": "labeled", "label": "aviato-consent:abc", "actor_type": "User", "actor_login": "al"}]
    grant = current_consent(events)
    assert grant is not None
    assert grant.diff_id == "abc"
    assert grant.actor_type == "User"
    assert grant.actor_login == "al"


def test_current_consent_revoked_returns_none() -> None:
    events = [
        {"action": "labeled", "label": "aviato-consent:abc", "actor_type": "User", "actor_login": "al"},
        {"action": "unlabeled", "label": "aviato-consent:abc", "actor_type": "User", "actor_login": "al"},
    ]
    assert current_consent(events) is None


def test_current_consent_later_revoke_in_history_wins() -> None:
    # a naive single-page read could miss the trailing revoke; full history must
    events = [
        {"action": "labeled", "label": "aviato-consent:abc", "actor_type": "User", "actor_login": "al"},
        {"action": "labeled", "label": "noise", "actor_type": "User", "actor_login": "al"},
        {"action": "unlabeled", "label": "aviato-consent:abc", "actor_type": "User", "actor_login": "al"},
    ]
    assert current_consent(events) is None


def test_current_consent_most_recent_grant_wins() -> None:
    events = [
        {"action": "labeled", "label": "aviato-consent:old", "actor_type": "User", "actor_login": "al"},
        {"action": "labeled", "label": "aviato-consent:new", "actor_type": "User", "actor_login": "bo"},
    ]
    grant = current_consent(events)
    assert grant.diff_id == "new"


def test_current_consent_ignores_non_consent_labels() -> None:
    assert current_consent([{"action": "labeled", "label": "bug", "actor_type": "User"}]) is None


def test_label_events_normalizes_timeline() -> None:
    timeline = [
        {"event": "labeled", "label": {"name": "aviato-consent:x"}, "actor": {"login": "al", "type": "User"}},
        {"event": "commented", "body": "hi"},
    ]
    events = _label_events(timeline)
    assert events == [{"action": "labeled", "label": "aviato-consent:x", "actor_type": "User", "actor_login": "al"}]


def test_adapter_satisfies_platform_protocol() -> None:
    assert isinstance(GitHubPlatform(), Platform)


def test_map_branch_settings_from_rules_matches_desired_shape() -> None:
    rules = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 2,
                "dismiss_stale_reviews_on_push": True,
                "required_review_thread_resolution": True,
            },
        },
    ]
    mapped = map_branch_settings(rules, {})
    assert mapped == {
        "requires_pull_request": True,
        "required_reviews": 2,
        "dismiss_stale_reviews": True,
        "require_thread_resolution": True,
        "block_force_push": True,
        "block_deletion": True,
        "required_status_checks": [],
    }


def test_map_branch_settings_reads_required_status_checks() -> None:
    protection = {"required_status_checks": {"strict": True, "contexts": ["common-lint / Common lint"]}}
    assert map_branch_settings([], protection)["required_status_checks"] == ["common-lint / Common lint"]


def test_map_branch_settings_reads_status_checks_from_ruleset() -> None:
    # #2: a repo protected by the branch RULESET (not classic protection) must still
    # surface its required checks — otherwise it maps to [] and shows false drift.
    rules = [
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [
                    {"context": "common-lint / Common lint"},
                    {"context": "ci / Python CI"},
                ],
            },
        }
    ]
    mapped = map_branch_settings(rules, {})
    assert mapped["required_status_checks"] == ["ci / Python CI", "common-lint / Common lint"]


def test_map_branch_settings_unions_classic_and_ruleset_checks() -> None:
    rules = [
        {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "ci / Python CI"}]}}
    ]
    protection = {"required_status_checks": {"contexts": ["common-lint / Common lint"]}}
    mapped = map_branch_settings(rules, protection)
    assert mapped["required_status_checks"] == ["ci / Python CI", "common-lint / Common lint"]


def test_to_branch_protection_payload_sets_required_checks() -> None:
    payload = to_branch_protection_payload({"required_status_checks": ["security / Security baseline heartbeat"]})
    assert payload["required_status_checks"]["contexts"] == ["security / Security baseline heartbeat"]
    assert payload["required_status_checks"]["strict"] is True


def test_map_branch_settings_keys_match_baseline_desired() -> None:
    from aviato.core.composition import resolve_profile
    from aviato.core.registry import Registry

    # required_status_checks is derived at composition time (not in the static
    # bundle), so compare the mapped keys against a fully-composed profile's desired
    # default-branch state — like-for-like, no spurious destructive drift.
    registry = Registry(Path("aviato/library"))
    desired = resolve_profile(registry, "python-library").settings["default_branch"]
    mapped = map_branch_settings([], {})
    assert set(mapped) == set(desired)


def test_map_branch_settings_unprotected() -> None:
    mapped = map_branch_settings([], {})
    assert mapped["requires_pull_request"] is False
    assert mapped["block_force_push"] is False
    assert mapped["block_deletion"] is False


def test_to_branch_protection_payload_api_shape() -> None:
    desired = {
        "requires_pull_request": True,
        "required_reviews": 1,
        "dismiss_stale_reviews": True,
        "require_thread_resolution": True,
        "block_force_push": True,
        "block_deletion": True,
    }
    payload = to_branch_protection_payload(desired)
    assert payload["required_pull_request_reviews"]["required_approving_review_count"] == 1
    assert payload["required_pull_request_reviews"]["dismiss_stale_reviews"] is True
    assert payload["allow_force_pushes"] is False  # block_force_push -> not allowed
    assert payload["allow_deletions"] is False
    assert payload["required_conversation_resolution"] is True
    assert payload["enforce_admins"] is True
    assert payload["restrictions"] is None
    assert "required_status_checks" in payload


def test_to_branch_protection_payload_no_pr_when_not_required() -> None:
    payload = to_branch_protection_payload({"requires_pull_request": False})
    assert payload["required_pull_request_reviews"] is None


def test_map_security_settings_from_live() -> None:
    from aviato.github_platform import map_security_settings

    sa = {
        "secret_scanning": {"status": "enabled"},
        "secret_scanning_push_protection": {"status": "disabled"},
        "dependabot_security_updates": {"status": "enabled"},
    }
    assert map_security_settings(sa) == {
        "secret_scanning": True,
        "secret_push_protection": False,
        "dependency_scanning": True,
    }


def test_to_security_payload_api_shape() -> None:
    from aviato.github_platform import to_security_payload

    payload = to_security_payload({"secret_scanning": True, "secret_push_protection": False})
    assert payload["secret_scanning"] == {"status": "enabled"}
    assert payload["secret_scanning_push_protection"] == {"status": "disabled"}


def test_probe_health_reads_issue_channel_and_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    def optional(endpoint, **__):
        if endpoint == "repos/o/r":
            return {"has_issues": True}
        if endpoint.startswith("repos/o/r/actions/artifacts"):
            return {"artifacts": [{"id": 1, "expired": False}]}
        return None

    monkeypatch.setattr(github, "gh_json_optional", optional)
    issue_channel, heartbeat = GitHubPlatform().probe_health("o/r")
    assert issue_channel is True
    assert heartbeat is True


def test_probe_health_heartbeat_false_when_no_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    def optional(endpoint, **__):
        if endpoint == "repos/o/r":
            return {"has_issues": False}
        return {"artifacts": []}

    monkeypatch.setattr(github, "gh_json_optional", optional)
    issue_channel, heartbeat = GitHubPlatform().probe_health("o/r")
    assert issue_channel is False
    assert heartbeat is False  # no heartbeat artifact → never ran → broken (§5.14)


def test_probe_health_heartbeat_false_when_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        github,
        "gh_json_optional",
        lambda endpoint, **__: (
            {"has_issues": True} if endpoint == "repos/o/r" else {"artifacts": [{"id": 1, "expired": True}]}
        ),
    )
    _, heartbeat = GitHubPlatform().probe_health("o/r")
    assert heartbeat is False


def test_read_settings_includes_security(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(github, "active_branch_rules", lambda repo, branch: [])
    monkeypatch.setattr(github, "classic_branch_protection", lambda repo, branch: {})
    monkeypatch.setattr(github, "repo_security_settings", lambda repo: {"secret_scanning": {"status": "enabled"}})
    settings = GitHubPlatform().read_settings("o/r")
    assert settings["secret_scanning"] is True
    assert "requires_pull_request" in settings  # branch fields still present


def test_read_settings_composes_gh_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(
        github,
        "active_branch_rules",
        lambda repo, branch: [{"type": "pull_request", "parameters": {"required_approving_review_count": 1}}],
    )
    monkeypatch.setattr(github, "classic_branch_protection", lambda repo, branch: {})
    # Mock the security read too, or read_settings makes a real `gh api` call (which
    # fails in CI with no GH_TOKEN); this test must stay fully hermetic.
    monkeypatch.setattr(github, "repo_security_settings", lambda repo: {})

    settings = GitHubPlatform().read_settings("o/r")
    # flat shape (matches the desired default_branch map the CLI passes)
    assert settings["required_reviews"] == 1
    assert "default_branch" not in settings


def test_read_settings_empty_when_no_default_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "default_branch", lambda repo: "")
    assert GitHubPlatform().read_settings("o/r") == {}


def test_get_issue_populates_consent_from_paginated_timeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "gh_json", lambda endpoint, **__: _route_gh_json(endpoint))
    monkeypatch.setattr(
        github,
        "gh_json_paginated",
        lambda endpoint, **__: [
            {"event": "labeled", "label": {"name": "aviato-consent:abc"}, "actor": {"login": "al", "type": "User"}}
        ],
    )
    issue = GitHubPlatform().get_issue("o/r", "aviato-settings-drift")
    assert issue is not None
    assert issue.consent_diff_id == "abc"
    assert issue.consent_actor_type == "User"
    assert issue.consent_role == "admin"
    assert issue.consent_role_lookup_ok is True


def _route_gh_json(endpoint: str):
    if endpoint.startswith("repos/o/r/issues?"):
        return [{"number": 7, "state": "open"}]
    if endpoint.endswith("/permission"):
        return {"permission": "admin"}
    return None


def test_get_issue_role_lookup_failure_is_not_authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    def gh_json(endpoint, **__):
        if endpoint.startswith("repos/o/r/issues?"):
            return [{"number": 7, "state": "open"}]
        return None  # permission lookup fails

    monkeypatch.setattr(github, "gh_json", gh_json)
    monkeypatch.setattr(
        github,
        "gh_json_paginated",
        lambda endpoint, **__: [
            {"event": "labeled", "label": {"name": "aviato-consent:abc"}, "actor": {"login": "al", "type": "User"}}
        ],
    )
    issue = GitHubPlatform().get_issue("o/r", "k")
    assert issue.consent_role_lookup_ok is False


def test_open_or_update_proposal_writes_files_and_pushes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **__):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(github, "run", fake_run)
    monkeypatch.setattr(github, "gh_json", lambda endpoint, **__: [])  # no existing PR

    platform = GitHubPlatform(workdir=tmp_path)
    branch = platform.open_or_update_proposal(
        "owner/repo", "aviato/sync/x", "Aviato sync", {"ruff.toml": "line-length = 120\n"}, "body"
    )

    assert branch == "aviato/sync/x"
    assert (tmp_path / "ruff.toml").read_text() == "line-length = 120\n"  # regenerated file written
    joined = [" ".join(c) for c in calls]
    assert any("git switch -C aviato/sync/x" in j for j in joined)
    assert any(j.startswith("git -c user.name=aviato-bot") and "commit" in j for j in joined)
    assert any("git push --force origin aviato/sync/x" in j for j in joined)
    assert any("gh pr create" in j for j in joined)


def test_open_or_update_proposal_skips_pr_create_when_pr_exists(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(
        github, "run", lambda cmd, **__: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    )
    monkeypatch.setattr(github, "gh_json", lambda endpoint, **__: [{"number": 5}])  # PR already open

    GitHubPlatform(workdir=tmp_path).open_or_update_proposal("owner/repo", "b", "t", {"f.txt": "x\n"}, "body")
    assert not any("pr create" in " ".join(c) for c in calls)  # push updated the existing PR


def test_apply_settings_issues_put_with_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(github, "default_branch", lambda repo: "main")
    monkeypatch.setattr(github, "classic_branch_protection", lambda repo, branch: {})

    written: dict[str, object] = {}

    def fake_run2(cmd, **__):
        captured["cmd"] = cmd
        if "--input" not in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        # capture the --input payload file contents
        import json as _json
        from pathlib import Path

        idx = cmd.index("--input")
        written["payload"] = _json.loads(Path(cmd[idx + 1]).read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(github, "run", fake_run2)
    GitHubPlatform().apply_settings(
        "o/r", {"requires_pull_request": True, "required_reviews": 2, "block_force_push": True}
    )
    cmd = captured["cmd"]
    assert "PUT" in cmd
    assert "repos/o/r/branches/main/protection" in cmd
    # translated to the branch-protection API shape, not the internal keys
    assert "required_reviews" not in written["payload"]
    assert written["payload"]["required_pull_request_reviews"]["required_approving_review_count"] == 2
    assert written["payload"]["allow_force_pushes"] is False
