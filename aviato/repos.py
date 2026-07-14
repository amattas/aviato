from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from .command import run

# R2-8: a slug is exactly `owner/repo` with safe chars — anything else (a `?`-bearing segment, a
# sub-path) is rejected so it can't later alter an API endpoint it's interpolated into.
_OWNER_REPO_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/(?:[A-Za-z0-9][A-Za-z0-9._-]*|\.[A-Za-z0-9_-][A-Za-z0-9._-]*)$"
)
# SCP-style / SSH remotes: `git@github.com:owner/repo(.git)`, `ssh://git@github.com/owner/repo`.
# Anchored at the start with the host as a literal so `notgithub.com/...` cannot match (the old
# unanchored `github.com` search did).
_SSH_REMOTE_RE = re.compile(r"^(?:ssh://)?(?:[^@/]+@)?github\.com[:/](?P<path>.+?)(?:\.git)?/?$")


def is_owner_repo_slug(value: str) -> bool:
    """True iff ``value`` is a clean two-segment ``owner/repo`` slug (R2-8, finding 23).

    The same rule ``normalize_slug`` enforces on remotes — exported so explicit slug
    ARGUMENTS (proposal paths) are validated identically instead of flowing raw into
    ``gh repo clone``."""
    if _OWNER_REPO_RE.fullmatch(value) is None:
        return False
    repository = value.partition("/")[2]
    return repository not in {".", ".."}


def normalize_slug(remote_url: str) -> str:
    """Extract the ``owner/repo`` slug from a GitHub remote, or ``""`` (R2-8/§2.14).

    Requires the host to be EXACTLY ``github.com`` (so ``notgithub.com/o/r`` is rejected) and the
    result to be a clean two-segment ``owner/repo`` (so a query-/path-shaped value can't slip
    through and corrupt a later API path)."""
    url = remote_url.strip()
    path: str | None = None
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        # urlparse.hostname is lowercased and strips any creds/port — exact match only.
        if parsed.hostname == "github.com":
            path = parsed.path.lstrip("/")
            if path.endswith(".git"):
                path = path[: -len(".git")]
    else:
        ssh = _SSH_REMOTE_RE.match(url)
        if ssh:
            path = ssh.group("path")
    if path is None:
        return ""
    path = path.strip("/")
    return path if is_owner_repo_slug(path) else ""


def git_root(path: Path) -> Path | None:
    result = run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def discover_repos(root: Path) -> list[Path]:
    root = root.resolve()
    repos: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        parts = set(current.parts)
        # Skip worktree checkouts and test fixtures (the and/or grouping is explicit:
        # skip if under .worktrees, OR under a tests/.../fixtures path).
        if ".worktrees" in parts or ("fixtures" in parts and "tests" in parts):
            dirnames[:] = []
            continue

        if ".git" in dirnames or ".git" in filenames:
            repo = git_root(current)
            if repo is not None:
                repos.add(repo)

        if ".git" in dirnames:
            dirnames.remove(".git")

    return sorted(repos)


def remote_url(repo: Path) -> str:
    for remote_name in ("origin", "origin-gh"):
        result = run(["git", "-C", str(repo), "config", "--get", f"remote.{remote_name}.url"], check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return ""


def current_branch(repo: Path) -> str:
    result = run(["git", "-C", str(repo), "branch", "--show-current"], check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def working_tree_clean(repo: Path) -> bool:
    """True iff the working tree has no staged/unstaged/untracked changes (§5.2 adopt).

    A non-git directory is treated as not-clean (fail-closed): adopt must run inside a
    git repository so the scaffold lands on a reviewable branch.
    """
    result = run(["git", "-C", str(repo), "status", "--porcelain"], check=False)
    if result.returncode != 0:
        return False
    return result.stdout.strip() == ""


def tags(repo: Path) -> list[str]:
    result = run(["git", "-C", str(repo), "tag", "--list"], check=False)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def workflow_files(repo: Path) -> str:
    workflow_dir = repo / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return ""
    names = sorted(path.name for path in workflow_dir.iterdir() if path.is_file() and path.suffix in {".yml", ".yaml"})
    return ",".join(names)
