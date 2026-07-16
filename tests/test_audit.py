from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from aviato import audit, cli
from aviato.audit import (
    AuditRow,
    _force_push_blocked,
    _requires_pr,
    audit_repo,
    render_json,
    render_tsv,
)
from aviato.cli import main
from aviato.github import GitHubAPIError

_POLICY = {"release": {"tag_pattern": r"^[0-9]+\.[0-9]+\.[0-9]+$"}}


def _git_init(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)


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
    monkeypatch.setattr("aviato.audit.github.default_branch", lambda slug: "main")
    monkeypatch.setattr(
        "aviato.audit.github.active_branch_rules",
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
    # 1.2.3 matches the bare pattern; v1.2.3 and nightly do not. invalid_tags is comma-joined,
    # so split and assert exact membership (not substring — "1.2.3" is a substring of "v1.2.3").
    flagged = row.invalid_tags.split(",")
    assert "v1.2.3" in flagged
    assert "nightly" in flagged
    assert "1.2.3" not in flagged  # the valid tag is not flagged


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


def test_audit_undeclared_repository_requires_explicit_pin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _git_init(tmp_path)

    assert main(["audit", "--repo", str(tmp_path)]) == 2
    assert "explicit --pin" in capsys.readouterr().err


def test_audit_undeclared_repository_uses_explicit_snapshot_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git_init(tmp_path)
    policy_root = tmp_path / "snapshot-policy"
    snapshot = SimpleNamespace(policy_root=policy_root)
    opened: list[tuple[Path, str]] = []
    policies: list[object] = []
    monkeypatch.setattr(
        cli,
        "_open_new_context",
        lambda root, pin: opened.append((root, pin)) or snapshot,
    )
    monkeypatch.setattr(
        cli,
        "_open_published_snapshot",
        lambda _pin: pytest.fail("target-bearing audit opened a bare snapshot"),
    )
    monkeypatch.setattr(cli, "load_policy", lambda root: {"root": str(root)})
    monkeypatch.setattr(
        cli,
        "audit_repos",
        lambda repos, *, root, policy: policies.append(policy) or [],
    )

    assert main(["audit", "--repo", str(tmp_path), "--pin", "1"]) == 0
    assert opened == [(tmp_path.resolve(), "1")]
    assert policies == [{"root": str(policy_root)}]


def test_audit_declared_repositories_each_use_their_own_pin_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos = [tmp_path / "one", tmp_path / "two"]
    for index, repo in enumerate(repos, start=1):
        _git_init(repo)
        declaration = repo / ".github/aviato.yaml"
        declaration.parent.mkdir()
        declaration.write_text(f"profile: python-library\nversion: {index}\nvariables: {{}}\n", encoding="utf-8")
    opened: list[tuple[Path, str]] = []

    def open_consumer(root: Path, declaration: object) -> object:
        opened.append((root, str(declaration.version)))  # type: ignore[attr-defined]
        return SimpleNamespace(policy_root=tmp_path / f"policy-{declaration.version}")  # type: ignore[attr-defined]

    monkeypatch.setattr(cli, "_open_consumer_context", open_consumer)
    monkeypatch.setattr(
        cli,
        "_open_published_snapshot",
        lambda _pin: pytest.fail("declared audit ignored the repository declaration"),
    )
    monkeypatch.setattr(cli, "load_policy", lambda root: {"root": str(root)})
    monkeypatch.setattr(cli, "audit_repos", lambda repos, *, root, policy: [])

    argv = ["audit", "--pin", "9"]
    for repo in repos:
        argv.extend(["--repo", str(repo)])
    assert main(argv) == 0
    assert opened == [(repo.resolve(), str(index)) for index, repo in enumerate(repos, start=1)]
