from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .core.selfcheck import core_import_violations, denylist_violations, load_denylist
from .paths import DENYLIST_FILE, REPO_ROOT
from .policy import load_policy, load_ruleset_manifest, load_yaml, release_tag_pattern
from .rulesets import render_all_rulesets

REQUIRED_FILES = [
    "policy.yml",
    "rulesets.yml",
    ".github/dependabot.yml",
    ".github/actions/validate-release-ref/action.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/reusable-python-ci.yml",
    ".github/workflows/reusable-node-ci.yml",
    ".github/workflows/reusable-swift-ci.yml",
    ".github/workflows/reusable-release-gate.yml",
    ".github/workflows/reusable-release.yml",
    ".github/workflows/reusable-docker-ghcr.yml",
    ".github/workflows/reusable-pypi-publish.yml",
    ".github/workflows/reusable-docs-pages.yml",
    ".github/workflows/reusable-app-store-connect.yml",
    ".github/workflows/reusable-security-baseline.yml",
    ".github/workflows/reusable-consumer-automation.yml",
    "templates/profile-python-service.yml",
    "templates/profile-python-library.yml",
    "templates/profile-python-component.yml",
    "templates/profile-node-service.yml",
    "templates/profile-swift-app.yml",
    "templates/consumer-automation.yml",
]

RELEASE_WORKFLOWS = [
    ".github/workflows/reusable-release-gate.yml",
    ".github/workflows/reusable-docker-ghcr.yml",
    ".github/workflows/reusable-pypi-publish.yml",
    ".github/workflows/reusable-docs-pages.yml",
    ".github/workflows/reusable-app-store-connect.yml",
]


def _check_policy_examples(policy: dict, errors: list[str]) -> None:
    pattern = re.compile(release_tag_pattern(policy))
    examples = policy.get("release", {}).get("examples", {})
    for value in examples.get("valid", []):
        if not pattern.fullmatch(str(value)):
            errors.append(f"policy valid release example does not match tag_pattern: {value}")
    for value in examples.get("invalid", []):
        if pattern.fullmatch(str(value)):
            errors.append(f"policy invalid release example matches tag_pattern: {value}")


def _check_release_pattern_drift(root: Path, policy: dict, errors: list[str]) -> None:
    pattern = release_tag_pattern(policy)

    action = load_yaml(root / ".github/actions/validate-release-ref/action.yml")
    action_pattern = action.get("inputs", {}).get("tag-pattern", {}).get("default")
    if action_pattern != pattern:
        errors.append(".github/actions/validate-release-ref/action.yml tag-pattern default differs from policy.yml")

    for rel_path in RELEASE_WORKFLOWS:
        workflow_text = (root / rel_path).read_text(encoding="utf-8")
        if pattern not in workflow_text:
            errors.append(f"{rel_path} does not embed the policy release tag pattern")

    rendered_tag_rulesets = [payload for payload in render_all_rulesets(root=root) if payload.get("target") == "tag"]
    for payload in rendered_tag_rulesets:
        for rule in payload.get("rules", []):
            if rule.get("type") == "tag_name_pattern" and rule.get("parameters", {}).get("pattern") != pattern:
                errors.append(f"rendered tag ruleset {payload.get('name')} differs from policy.yml")


def _walk_jobs(data: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = data.get("jobs", {})
    if not isinstance(jobs, dict):
        return []
    return [job for job in jobs.values() if isinstance(job, dict)]


def _check_workflow_yaml(root: Path, errors: list[str]) -> None:
    for rel_dir in (".github/workflows", "templates"):
        for path in sorted((root / rel_dir).glob("*.yml")):
            try:
                load_yaml(path)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"invalid YAML in {path.relative_to(root)}: {exc}")


def _check_template_references(root: Path, errors: list[str]) -> None:
    workflow_dir = root / ".github/workflows"
    workflow_files = {path.name for path in workflow_dir.glob("*.yml")}
    reference_re = re.compile(r"^amattas/aviato/\.github/workflows/([^@]+)@(.+)$")

    for path in sorted((root / "templates").glob("*.yml")):
        data = load_yaml(path)
        for job in _walk_jobs(data):
            value = job.get("uses")
            if not isinstance(value, str):
                continue
            match = reference_re.match(value)
            if not match:
                continue
            workflow_file, ref = match.groups()
            if workflow_file not in workflow_files:
                errors.append(f"{path.relative_to(root)} references missing workflow {workflow_file}")
            if not ref:
                errors.append(f"{path.relative_to(root)} references {workflow_file} without a ref")


def _check_release_workflow_contract(root: Path, errors: list[str]) -> None:
    for rel_path in RELEASE_WORKFLOWS:
        text = (root / rel_path).read_text(encoding="utf-8")
        if "release/*" in text or "release/latest" in text:
            errors.append(f"{rel_path} contains legacy release branch support")
        if "repository: amattas/aviato" in text:
            errors.append(
                f"{rel_path} checks out Aviato by repository name; this can drift from the pinned workflow ref"
            )
        if "GITHUB_REF_TYPE" not in text or "tag" not in text:
            errors.append(f"{rel_path} does not visibly validate that it runs from a tag ref")


def _check_core_agnosticism(core_dir: Path, denylist_file: Path, errors: list[str]) -> None:
    """Enforce the §9b falsifiable agnosticism: no plug-in import edge, no denylisted token."""
    for violation in core_import_violations(core_dir):
        errors.append(f"core import edge into plug-in tree: {violation}")
    denylist = load_denylist(denylist_file)
    for violation in denylist_violations(core_dir, denylist):
        errors.append(f"core names a denylisted identifier: {violation}")


def validate(root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []

    for rel_path in REQUIRED_FILES:
        if not (root / rel_path).exists():
            errors.append(f"missing required file: {rel_path}")

    try:
        policy = load_policy(root)
        load_ruleset_manifest(root)
    except Exception as exc:  # noqa: BLE001 - report validation failures without hiding context
        return [f"failed to load policy/manifest: {exc}"]

    for ruleset_path in sorted((root / "rulesets").glob("*.json")):
        try:
            with ruleset_path.open("r", encoding="utf-8") as handle:
                json.load(handle)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"invalid JSON in {ruleset_path}: {exc}")

    _check_policy_examples(policy, errors)
    _check_release_pattern_drift(root, policy, errors)
    _check_workflow_yaml(root, errors)
    _check_template_references(root, errors)
    _check_release_workflow_contract(root, errors)
    _check_core_agnosticism(root / "aviato" / "core", root / DENYLIST_FILE.relative_to(REPO_ROOT), errors)

    return errors
