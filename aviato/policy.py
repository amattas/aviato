from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .paths import REPO_ROOT


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_policy(root: Path = REPO_ROOT) -> dict[str, Any]:
    return load_yaml(root / "policy.yml")


def load_ruleset_manifest(root: Path = REPO_ROOT) -> dict[str, Any]:
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


def default_required_approvals(policy: dict[str, Any]) -> int:
    value = get_path(policy, "branch.required_approvals_default")
    if not isinstance(value, int) or value < 0:
        raise ValueError("branch.required_approvals_default must be a non-negative integer")
    return value
