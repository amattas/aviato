from __future__ import annotations

import os
import re
from pathlib import Path

from .command import run

GITHUB_REMOTE_RE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$")


def normalize_slug(remote_url: str) -> str:
    match = GITHUB_REMOTE_RE.search(remote_url.strip())
    return match.group(1) if match else ""


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
        if ".worktrees" in parts or "fixtures" in parts and "tests" in parts:
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
