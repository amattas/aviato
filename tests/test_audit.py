from __future__ import annotations

import json
from pathlib import Path

import pytest

from aviato import audit
from aviato.audit import (
    AuditRow,
    _force_push_blocked,
    _requires_pr,
    audit_repo,
    render_json,
    render_tsv,
)
from aviato.github import GitHubAPIError

_POLICY = {"release": {"tag_pattern": r"^[0-9]+\.[0-9]+\.[0-9]+$"}}


def test_requires_pr_from_ruleset() -> None:
    assert _requires_pr([{"type": "pull_request"}], {}) is True


def test_requires_pr_from_classic_protection() -> None:
    assert _requires_pr([], {"required_pull_request_reviews": {"required_approving_review_count": 1}}) is True


def test_requires_pr_false_when_neither() -> None:
    assert _requires_pr([], {}) is False
    # A null classic block must not count as protection (would be a false "yes").
    assert _requires_pr([], {"required_pull_request_reviews": None}) is False


def test_force_push_blocked_from_ruleset() -> None:
    assert _force_push_blocked([{"type": "non_fast_forward"}], {}) is True


def test_force_push_blocked_from_classic_protection() -> None:
    # allow_force_pushes disabled => force push is blocked.
    assert _force_push_blocked([], {"allow_force_pushes": {"enabled": False}}) is True


def test_force_push_not_blocked_when_allowed() -> None:
    assert _force_push_blocked([], {"allow_force_pushes": {"enabled": True}}) is False
    assert _force_push_blocked([], {}) is False


def test_audit_repo_no_remote(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(audit, "remote_url", lambda repo: "")
    monkeypatch.setattr(audit, "normalize_slug", lambda remote: "")
    monkeypatch.setattr(audit, "tags", lambda repo: [])
    monkeypatch.setattr(audit, "current_branch", lambda repo: "main")
    monkeypatch.setattr(audit, "workflow_files", lambda repo: "")
    row = audit_repo(tmp_path, root=tmp_path, policy=_POLICY)
    assert row.default_branch_requires_pr == "NO_REMOTE"
    assert row.tag_ruleset == "NO_REMOTE"


def test_audit_repo_api_error_when_reads_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # A fail-closed read raising mid-audit degrades the row to API_ERROR, never crashes.
    monkeypatch.setattr(audit, "remote_url", lambda repo: "git@github.com:o/r.git")
    monkeypatch.setattr(audit, "normalize_slug", lambda remote: "o/r")
    monkeypatch.setattr(audit, "tags", lambda repo: [])
    monkeypatch.setattr(audit, "current_branch", lambda repo: "main")
    monkeypatch.setattr(audit, "workflow_files", lambda repo: "ci.yml")
    monkeypatch.setattr(audit.github, "default_branch", lambda slug: "main")
    monkeypatch.setattr(
        audit.github,
        "active_branch_rules",
        lambda slug, branch: (_ for _ in ()).throw(GitHubAPIError("rules", 1, "boom")),
    )
    row = audit_repo(tmp_path, root=tmp_path, policy=_POLICY)
    assert row.default_branch_requires_pr == "API_ERROR"


def test_audit_repo_flags_invalid_tags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(audit, "remote_url", lambda repo: "")
    monkeypatch.setattr(audit, "normalize_slug", lambda remote: "")
    monkeypatch.setattr(audit, "tags", lambda repo: ["1.2.3", "v1.2.3", "nightly"])
    monkeypatch.setattr(audit, "current_branch", lambda repo: "main")
    monkeypatch.setattr(audit, "workflow_files", lambda repo: "")
    row = audit_repo(tmp_path, root=tmp_path, policy=_POLICY)
    # 1.2.3 matches the bare pattern; v1.2.3 and nightly do not.
    assert "v1.2.3" in row.invalid_tags
    assert "nightly" in row.invalid_tags
    assert "1.2.3" not in row.invalid_tags.replace("v1.2.3", "")


def test_render_tsv_has_header_and_row() -> None:
    row = AuditRow("p", "o/r", "main", "main", "ci.yml", "yes", "yes", "Common", "")
    tsv = render_tsv([row])
    lines = tsv.splitlines()
    assert lines[0].split("\t")[0] == "path"
    assert "o/r" in lines[1]


def test_render_json_roundtrips() -> None:
    row = AuditRow("p", "o/r", "main", "main", "ci.yml", "yes", "no", "no", "")
    data = json.loads(render_json([row]))
    assert data[0]["slug"] == "o/r"
    assert data[0]["force_push_blocked"] == "no"
