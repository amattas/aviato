from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .paths import POLICY_DATA_ROOT
from .repos import is_owner_repo_slug


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_policy(root: Path = POLICY_DATA_ROOT) -> dict[str, Any]:
    """Load ``policy.yml`` from the packaged data root (ships in the wheel; §5.6/§11.3).

    ``root`` is the directory CONTAINING the data files. The runtime default is the installed
    package's own ``aviato/library``; validation passes the in-repo ``<repo>/aviato/library``
    for the copy it is checking.
    """
    return load_yaml(root / "policy.yml")


def load_ruleset_manifest(root: Path = POLICY_DATA_ROOT) -> dict[str, Any]:
    return load_yaml(root / "rulesets.yml")


def get_path(data: dict[str, Any], dotted_path: str) -> Any:
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing policy path: {dotted_path}")
        current = current[part]
    return current


def release_tag_pattern(policy: dict[str, Any]) -> str:
    value = get_path(policy, "release.tag_pattern")
    if not isinstance(value, str) or not value:
        raise ValueError("release.tag_pattern must be a non-empty string")
    return value


def library_repository(policy: dict[str, Any]) -> str:
    """Return the canonical GitHub ``owner/repository`` identity for the Library."""
    value = get_path(policy, "library.repository")
    if not isinstance(value, str) or not is_owner_repo_slug(value):
        raise ValueError("library.repository must be a GitHub owner/repository slug")
    return value


def default_required_approvals(policy: dict[str, Any]) -> int:
    value = get_path(policy, "branch.required_approvals_default")
    # R3-17: `bool` is an `int` subclass, so `required_approvals_default: true` would pass an
    # `isinstance(int)` check and render as 1. Require a real int, rejecting bool.
    if type(value) is not int or value < 0:
        raise ValueError("branch.required_approvals_default must be a non-negative integer (not a boolean)")
    return value
