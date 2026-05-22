from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .core.selfcheck import core_import_violations, denylist_violations, load_denylist
from .paths import DENYLIST_FILE, REPO_ROOT
from .policy import default_required_approvals, load_policy, load_ruleset_manifest, load_yaml, release_tag_pattern
from .rulesets import render_all_rulesets

REQUIRED_FILES = [
    "policy.yml",
    "rulesets.yml",
    ".github/dependabot.yml",
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
    ".github/workflows/reusable-common-lint.yml",
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
    description = policy.get("release", {}).get("tag_format_description")

    for rel_path in RELEASE_WORKFLOWS:
        workflow_text = (root / rel_path).read_text(encoding="utf-8")
        # Bind the check to the OPERATIVE assignment (the TAG_PATTERN env actually fed to
        # the `=~` match), not just any occurrence — so the policy pattern sitting in a
        # comment while a different literal is in use would not silently pass.
        if f"TAG_PATTERN: '{pattern}'" not in workflow_text:
            errors.append(f"{rel_path} does not embed the policy release tag pattern in its TAG_PATTERN env")
        # The operator-facing description must match policy; otherwise the failure
        # message can advertise a tag format the pattern rejects (e.g. a leading v).
        if f"TAG_FORMAT_DESCRIPTION: '{description}'" not in workflow_text:
            errors.append(f"{rel_path} TAG_FORMAT_DESCRIPTION env differs from policy.yml tag_format_description")

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


def _yaml_files(directory: Path) -> list[Path]:
    """All YAML files in a directory. GitHub Actions accepts both extensions, so a
    misnamed ``*.yaml`` workflow must not escape parse/drift/reference checks (M4)."""
    return sorted(p for ext in ("*.yml", "*.yaml") for p in directory.glob(ext))


def _check_workflow_yaml(root: Path, errors: list[str]) -> None:
    for rel_dir in (".github/workflows", "templates"):
        for path in _yaml_files(root / rel_dir):
            try:
                load_yaml(path)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"invalid YAML in {path.relative_to(root)}: {exc}")


def _check_template_references(root: Path, errors: list[str]) -> None:
    workflow_dir = root / ".github/workflows"
    workflow_files = {path.name for path in _yaml_files(workflow_dir)}
    reference_re = re.compile(r"^amattas/aviato/\.github/workflows/([^@]+)@(.+)$")

    for path in _yaml_files(root / "templates"):
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
        # Require the OPERATIVE guard (the shell comparison that actually gates publishing
        # on a tag ref), not a bare GITHUB_REF_TYPE mention that could sit in a comment.
        if '"${GITHUB_REF_TYPE}" != "tag"' not in text:
            errors.append(f"{rel_path} does not gate publishing on a tag ref (missing GITHUB_REF_TYPE != tag guard)")


def _check_baseline_settings_drift(root: Path, policy: dict, errors: list[str]) -> None:
    """The desired-state baseline must not drift from policy.yml's required approvals.

    ``policy.yml`` is the single source of truth for the default required PR approvals;
    the settings baseline duplicates it as desired state, so it is drift-checked here
    alongside the ruleset/action/workflow copies.
    """
    baseline_path = root / "aviato" / "library" / "bundles" / "settings" / "baseline.yaml"
    if not baseline_path.is_file():
        return
    baseline = load_yaml(baseline_path)
    default_branch = baseline.get("settings", {}).get("default_branch", {})
    if "required_reviews" not in default_branch:
        return
    expected = default_required_approvals(policy)
    if default_branch.get("required_reviews") != expected:
        errors.append(
            f"settings baseline required_reviews ({default_branch.get('required_reviews')}) differs from "
            f"policy.yml required approvals ({expected})"
        )


def _check_core_agnosticism(core_dir: Path, denylist_file: Path, errors: list[str]) -> None:
    """Enforce the §9b falsifiable agnosticism: no plug-in import edge, no denylisted token."""
    for violation in core_import_violations(core_dir):
        errors.append(f"core import edge into plug-in tree: {violation}")
    denylist = load_denylist(denylist_file)
    for violation in denylist_violations(core_dir, denylist):
        errors.append(f"core names a denylisted identifier: {violation}")


def _check_action_pins(root: Path, errors: list[str]) -> None:
    """§11.3: third-party actions/tools invoked by any pipeline are pinned by digest."""
    from .core.actionpins import action_pin_violations

    for violation in action_pin_violations(root):
        errors.append(f"unpinned third-party action/tool (§11.3): {violation}")


# The documented copyable caller templates are RENDERED from the authoritative scaffold
# bundles with these example variables — they are not a hand-maintained second copy.
# The parity check below fails if they drift, so editing a scaffold caller forces a
# regenerate (scripts/regen-templates.py).
_TEMPLATE_EXAMPLE_VARS: dict[str, dict[str, str]] = {
    "python-library": {"distribution-name": "your-distribution", "import-name": "your_package"},
    "python-service": {"image-name": "your-image", "import-name": "your_package"},
    "python-component": {"import-name": "your_package"},
    "node-service": {"project-name": "your-app", "language-variant": "typescript"},
    "swift-app": {
        "product-scheme": "App",
        "bundle-identifier": "com.example.app",
        "team-id": "TEAMID1234",
        "export-method": "app-store",
    },
}
_PROFILE_TEMPLATE_FILES = {
    "python-library": "templates/profile-python-library.yml",
    "python-service": "templates/profile-python-service.yml",
    "python-component": "templates/profile-python-component.yml",
    "node-service": "templates/profile-node-service.yml",
    "swift-app": "templates/profile-swift-app.yml",
}


def _rendered_caller(root: Path, profile: str, output: str) -> str | None:
    from .core.onboarding import resolved_artifacts
    from .core.registry import Registry

    registry = Registry(root / "aviato" / "library")
    artifacts = resolved_artifacts(registry, profile, _TEMPLATE_EXAMPLE_VARS[profile], pin="main", docs=False)
    return next((a.body for a in artifacts if a.output == output), None)


def _check_template_scaffold_parity(root: Path, errors: list[str]) -> None:
    """Documented caller templates must equal the rendered scaffold output (no drift)."""
    checks = [(p, f, ".github/workflows/aviato-ci.yml") for p, f in _PROFILE_TEMPLATE_FILES.items()]
    checks.append(("python-library", "templates/consumer-automation.yml", ".github/workflows/aviato-drift.yml"))
    for profile, rel_path, output in checks:
        path = root / rel_path
        if not path.exists():
            continue  # absence is already reported by the REQUIRED_FILES check
        expected = _rendered_caller(root, profile, output)
        if expected is None:
            errors.append(f"{rel_path}: profile {profile!r} no longer produces {output}")
        elif path.read_text(encoding="utf-8") != expected:
            errors.append(
                f"{rel_path} is stale: it does not match the rendered scaffold caller for "
                f"{profile!r}. Regenerate with scripts/regen-templates.py."
            )


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
    _check_baseline_settings_drift(root, policy, errors)
    _check_core_agnosticism(root / "aviato" / "core", root / DENYLIST_FILE.relative_to(REPO_ROOT), errors)
    _check_action_pins(root, errors)
    _check_template_scaffold_parity(root, errors)

    return errors
