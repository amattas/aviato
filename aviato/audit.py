from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from . import github
from .github import GitHubAPIError
from .policy import release_tag_pattern
from .repos import current_branch, discover_repos, normalize_slug, remote_url, tags, workflow_files

# R3-14/§5.9/§6.1: a bare floating-major tag (`1`, `2`) is a SANCTIONED release alias (the tag
# ruleset explicitly excludes it from the exact-SemVer pattern), so it is not an "invalid" tag.
_FLOATING_MAJOR_RE = re.compile(r"[0-9]+")


@dataclass
class AuditRow:
    path: str
    slug: str
    default_branch: str
    local_branch: str
    workflows: str
    default_branch_requires_pr: str
    force_push_blocked: str
    tag_ruleset: str
    invalid_tags: str


def _requires_pr(rules: list[dict], protection: dict) -> bool:
    rules_pr = any(rule.get("type") == "pull_request" for rule in rules)
    classic_pr = (
        "required_pull_request_reviews" in protection and protection.get("required_pull_request_reviews") is not None
    )
    return rules_pr or classic_pr


def _force_push_blocked(rules: list[dict], protection: dict) -> bool:
    rules_nff = any(rule.get("type") == "non_fast_forward" for rule in rules)
    allow_force_pushes = protection.get("allow_force_pushes")
    classic_force_blocked = isinstance(allow_force_pushes, dict) and allow_force_pushes.get("enabled") is not True
    return rules_nff or classic_force_blocked


def audit_repo(repo: Path, *, root: Path, policy: dict) -> AuditRow:
    pattern = re.compile(release_tag_pattern(policy))
    repo_path = repo.resolve()
    root_path = root.resolve()
    rel = "." if repo_path == root_path else str(repo_path).removeprefix(str(root_path) + "/")
    remote = remote_url(repo)
    slug = normalize_slug(remote)
    invalid_tags = ",".join(
        tag for tag in tags(repo) if not pattern.fullmatch(tag) and not _FLOATING_MAJOR_RE.fullmatch(tag)
    )[:500]
    local_branch = current_branch(repo)
    workflows = workflow_files(repo)

    if not slug:
        return AuditRow(rel, "", "", local_branch, workflows, "NO_REMOTE", "NO_REMOTE", "NO_REMOTE", invalid_tags)

    try:
        default = github.default_branch(slug)
    except GitHubAPIError:
        default = ""

    if not default:
        return AuditRow(rel, slug, "", local_branch, workflows, "API_ERROR", "API_ERROR", "API_ERROR", invalid_tags)

    # These reads fail closed (§2.7): an ambiguous (auth/5xx/rate-limit) read raises
    # rather than reporting a false "no protection". Degrade the whole row to
    # API_ERROR rather than crash the audit, so one flaky repo doesn't sink the run.
    try:
        rules = github.active_branch_rules(slug, default)
        protection = github.classic_branch_protection(slug, default)
        tag_rulesets = github.tag_ruleset_names(slug)
    except GitHubAPIError:
        err = "API_ERROR"
        return AuditRow(rel, slug, default, local_branch, workflows, err, err, err, invalid_tags)

    return AuditRow(
        path=rel,
        slug=slug,
        default_branch=default,
        local_branch=local_branch,
        workflows=workflows,
        default_branch_requires_pr="yes" if _requires_pr(rules, protection) else "no",
        force_push_blocked="yes" if _force_push_blocked(rules, protection) else "no",
        tag_ruleset=",".join(tag_rulesets) if tag_rulesets else "no",
        invalid_tags=invalid_tags,
    )


def audit_repos(repos: Iterable[Path], *, root: Path, policy: dict) -> list[AuditRow]:
    return [audit_repo(repo, root=root, policy=policy) for repo in repos]


def discover_and_audit(root: Path, *, policy: dict) -> list[AuditRow]:
    return audit_repos(discover_repos(root), root=root, policy=policy)


def render_tsv(rows: list[AuditRow]) -> str:
    fields = list(AuditRow.__dataclass_fields__.keys())
    lines = ["\t".join(fields)]
    for row in rows:
        values = [str(getattr(row, field)) for field in fields]
        lines.append("\t".join(values))
    return "\n".join(lines)


def render_json(rows: list[AuditRow]) -> str:
    return json.dumps([asdict(row) for row in rows], indent=2)
