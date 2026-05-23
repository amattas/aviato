from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .core.selfcheck import core_import_violations, denylist_violations, load_denylist
from .paths import DENYLIST_FILE, REPO_ROOT
from .policy import (
    default_required_approvals,
    get_path,
    load_policy,
    load_ruleset_manifest,
    load_yaml,
    release_tag_pattern,
)

REQUIRED_FILES = [
    "aviato/library/policy.yml",
    "aviato/library/rulesets.yml",
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

# This Library's own GitHub slug. Centralized (was duplicated as literals across the
# template-reference and release-workflow-contract checks); it is the Library's own
# repository identity, not consumer data, so a single constant is the source of truth.
LIBRARY_SLUG = "amattas/aviato"


def _check_policy_examples(policy: dict, errors: list[str]) -> None:
    pattern = re.compile(release_tag_pattern(policy))
    examples = policy.get("release", {}).get("examples", {})
    for value in examples.get("valid", []):
        if not pattern.fullmatch(str(value)):
            errors.append(f"policy valid release example does not match tag_pattern: {value}")
    for value in examples.get("invalid", []):
        if pattern.fullmatch(str(value)):
            errors.append(f"policy invalid release example matches tag_pattern: {value}")


def _check_release_pattern_drift(root: Path, data_root: Path, policy: dict, errors: list[str]) -> None:
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

    # Drift-check the STATIC ruleset templates, not the rendered output. Rendering injects
    # the policy value (rulesets._patch_*), so comparing the rendered payload to policy is a
    # tautology that can never fail — the literal in the JSON file could drift to anything and
    # stay green. Comparing the on-disk literal to policy makes it a genuine "every embedded copy
    # stays in sync" guard (§9), even though render re-injects it. review #24: this covers EVERY
    # patched path (the branch ruleset's required_approving_review_count too), not just the tag
    # pattern — the branch approval literal in protect-default-branch.json was previously unchecked.
    # patch key -> (rule type carrying it, parameter name within that rule).
    _PATCH_RULE_PARAM = {
        "tag_name_pattern": ("tag_name_pattern", "pattern"),
        "required_approving_review_count": ("pull_request", "required_approving_review_count"),
    }
    for item in load_ruleset_manifest(data_root).get("rulesets", []):
        raw = json.loads((data_root / item["file"]).read_text(encoding="utf-8"))
        for patch_key, policy_path in item.get("patch", {}).items():
            mapping = _PATCH_RULE_PARAM.get(patch_key)
            if mapping is None or not policy_path:
                continue
            rule_type, param_name = mapping
            expected = get_path(policy, policy_path)
            for rule in raw.get("rules", []):
                if rule.get("type") == rule_type:
                    actual = rule.get("parameters", {}).get(param_name)
                    if actual != expected:
                        errors.append(
                            f"{item['file']} {patch_key} {actual!r} differs from policy.yml "
                            f"({policy_path} = {expected!r}); keep the static ruleset template in sync with policy"
                        )


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
    reference_re = re.compile(rf"^{re.escape(LIBRARY_SLUG)}/\.github/workflows/([^@]+)@(.+)$")

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
        if f"repository: {LIBRARY_SLUG}" in text:
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


def _check_baseline_settings_keys(root: Path, errors: list[str]) -> None:
    """Every baseline default-branch/security key must be one the apply path can WRITE (§5.1).

    A key the binding's payload builders don't consume would be silently ignored at apply time
    yet still surface as drift — never-converging phantom drift. Catch a Library-side typo or an
    unmodeled key here, loudly, at CI time (consumer-override typos are filtered at runtime by
    ``_desired_settings``).
    """
    baseline_path = root / "aviato" / "library" / "bundles" / "settings" / "baseline.yaml"
    if not baseline_path.is_file():
        return
    from .github_platform import RECONCILABLE_SETTING_KEYS

    settings = load_yaml(baseline_path).get("settings", {})
    declared = set(settings.get("default_branch", {})) | set(settings.get("security", {}))
    unknown = sorted(declared - set(RECONCILABLE_SETTING_KEYS))
    if unknown:
        errors.append(
            f"settings baseline declares unreconcilable key(s) {unknown}: the apply path "
            f"(to_branch_protection_payload / to_security_payload) does not write them, so they "
            f"would be phantom drift. Add them to the binding or remove the typo (§5.1)."
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
    from .plugins.actionpins import action_pin_violations

    for violation in action_pin_violations(root):
        errors.append(f"unpinned third-party action/tool (§11.3): {violation}")


# The documented copyable caller templates are RENDERED from the authoritative scaffold
# bundles with these example variables — they are not a hand-maintained second copy.
# The parity check below fails if they drift, so editing a scaffold caller forces a
# regenerate (scripts/regen-templates.py).
_TEMPLATE_EXAMPLE_VARS: dict[str, dict[str, str]] = {
    "python-library": {"distribution-name": "your-distribution", "import-name": "your_package"},
    # A container service declares only the GHCR image target — no wheel/import name (§13.2).
    "python-service": {"image-name": "your-image"},
    "python-component": {"distribution-name": "your-distribution", "import-name": "your_package"},
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


def _check_scaffold_workflow_yaml(root: Path, errors: list[str]) -> None:
    """Each RENDERED scaffold workflow body must be valid YAML (§16).

    The scaffold ``wf-*.yml`` bodies carry ``{{ var }}`` placeholders, so they aren't valid YAML
    until rendered — `_check_workflow_yaml` only parses committed `.github/workflows`/`templates`.
    Render each profile's caller workflows (docs off AND on) with the example vars and parse them,
    so a syntax error in a scaffolded caller is caught here, not first in a consumer's repo.
    """
    from .core.onboarding import resolved_artifacts
    from .core.registry import Registry

    # review #25: the docs callers (rendered only with docs=True) have NO committed template, so
    # _check_template_references never validates their `uses:` targets. Verify here that every
    # reusable-workflow ref in a rendered caller resolves to a workflow that actually exists, so a
    # renamed/deleted reusable workflow can't ship a broken caller to consumers undetected.
    workflow_files = {path.name for path in _yaml_files(root / ".github/workflows")}
    reference_re = re.compile(rf"^{re.escape(LIBRARY_SLUG)}/\.github/workflows/([^@]+)@(.+)$")

    registry = Registry(root / "aviato" / "library")
    for profile, example_vars in _TEMPLATE_EXAMPLE_VARS.items():
        for docs in (False, True):
            try:
                artifacts = resolved_artifacts(registry, profile, example_vars, pin="main", docs=docs)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"scaffold render failed for {profile!r} (docs={docs}): {exc}")
                continue
            for artifact in artifacts:
                if artifact.seed_once or not artifact.output.startswith(".github/workflows/"):
                    continue
                if not artifact.output.endswith((".yml", ".yaml")):
                    continue
                try:
                    doc = yaml.safe_load(artifact.body)
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        f"rendered scaffold workflow {artifact.output} ({profile!r}, docs={docs}) "
                        f"is invalid YAML: {exc}"
                    )
                    continue
                for job in _walk_jobs(doc if isinstance(doc, dict) else {}):
                    uses = job.get("uses")
                    match = reference_re.match(uses) if isinstance(uses, str) else None
                    if match and match.group(1) not in workflow_files:
                        errors.append(
                            f"rendered scaffold workflow {artifact.output} ({profile!r}, docs={docs}) "
                            f"references missing reusable workflow {match.group(1)}"
                        )


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


# Workflows that embed an inline `highest.py` reimplementation of the §8.14/§13.2 monotonic
# alias guard (kept inline to avoid a self-reference install in the deploy job). The parity
# check below proves each inline copy still agrees with aviato.core.versioning.is_highest, so a
# silent divergence (e.g. prerelease ranking) cannot let an older release move `latest`/docs back.
_MONOTONIC_ALIAS_WORKFLOWS = [
    ".github/workflows/reusable-docker-ghcr.yml",
    ".github/workflows/reusable-docs-pages.yml",
]

# (candidate, existing tags). Expected results are computed from is_highest itself, so the check
# is "the inline copy agrees with core" — chosen to exercise the discriminating cases: ordering,
# equality/ties, prerelease ranking (final > beta > alpha), v-prefix, and unparseable-tag skip.
_MONOTONIC_CASES = [
    ("1.2.3", ["1.0.0", "1.2.2"]),
    ("1.2.3", ["1.2.3", "2.0.0"]),
    ("1.2.3", []),
    ("1.2.3", ["1.2.3"]),
    ("1.0.0", ["1.0.0-beta1", "1.0.0-alpha1"]),
    ("1.0.0-beta1", ["1.0.0"]),
    ("1.0.0-beta2", ["1.0.0-beta1"]),
    ("1.0.0-alpha1", ["1.0.0-beta1"]),
    ("v1.2.3", ["1.2.2"]),
    ("2.0.0", ["garbage", "not-a-tag", "1.9.9"]),
    ("not-a-version", ["1.0.0"]),
    # review #10: MULTI-DIGIT components in every position, so a string-vs-int comparator drift in
    # an inline copy (e.g. ranking "1.0.0-beta10" BELOW "1.0.0-beta2", or "1.10.0" below "1.2.0")
    # is caught — single-digit cases give the same answer under string and int comparison and
    # would let that exact backward-alias regression slip through the parity check.
    ("1.0.0-beta10", ["1.0.0-beta2"]),
    ("1.0.0-beta2", ["1.0.0-beta10"]),
    ("1.10.0", ["1.2.0"]),
    ("1.2.0", ["1.10.0"]),
    ("1.0.10", ["1.0.2"]),
    ("10.0.0", ["9.0.0"]),
    ("9.0.0", ["10.0.0"]),
]


def _extract_py_heredoc(run_text: str) -> str | None:
    """Return the body of a ``<<'PY' ... PY`` heredoc in a parsed step ``run`` block, or None.

    The YAML loader already dedents the block to its base indent, so the captured lines are
    valid Python (relative indentation preserved).
    """
    lines = run_text.splitlines()
    for i, line in enumerate(lines):
        if "<<'PY'" in line:
            body: list[str] = []
            for sub in lines[i + 1 :]:
                if sub.strip() == "PY":
                    return "\n".join(body)
                body.append(sub)
            return None
    return None


def _check_monotonic_alias_parity(root: Path, errors: list[str]) -> None:
    """The inline `highest.py` in the deploy workflows must match core's is_highest (§8.14/§13.2)."""
    import subprocess
    import sys

    from .core.versioning import is_highest

    for rel_path in _MONOTONIC_ALIAS_WORKFLOWS:
        path = root / rel_path
        if not path.exists():
            continue  # absence already reported by REQUIRED_FILES
        try:
            doc = load_yaml(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel_path}: could not parse for monotonic-alias parity: {exc}")
            continue
        runs = [
            step["run"]
            for job in (doc.get("jobs") or {}).values()
            if isinstance(job, dict)
            for step in (job.get("steps") or [])
            if isinstance(step, dict) and isinstance(step.get("run"), str)
        ]
        snippet = next((s for run in runs if (s := _extract_py_heredoc(run)) is not None), None)
        if snippet is None:
            errors.append(
                f"{rel_path}: the inline `highest.py` monotonic-alias guard is missing "
                "(§8.14/§13.2); an alias could move backward unchecked."
            )
            continue
        for candidate, existing in _MONOTONIC_CASES:
            result = subprocess.run(
                [sys.executable, "-c", snippet, candidate],
                input="\n".join(existing),
                capture_output=True,
                text=True,
            )
            inline = result.stdout.strip()
            expected = "true" if is_highest(candidate, existing) else "false"
            if inline != expected:
                errors.append(
                    f"{rel_path}: inline highest.py disagrees with core is_highest for "
                    f"candidate={candidate!r} existing={existing!r} (inline={inline!r}, "
                    f"core={expected!r}); the copy has drifted from aviato.core.versioning."
                )


def validate(root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []

    for rel_path in REQUIRED_FILES:
        if not (root / rel_path).exists():
            errors.append(f"missing required file: {rel_path}")

    # Policy + ruleset DATA now lives in the package (`aviato/library`) so it ships in the wheel
    # (§5.6/§11.3); validate the IN-REPO copy under the operated root.
    data_root = root / "aviato" / "library"
    try:
        policy = load_policy(data_root)
        load_ruleset_manifest(data_root)
    except Exception as exc:  # noqa: BLE001 - report validation failures without hiding context
        return [f"failed to load policy/manifest: {exc}"]

    for ruleset_path in sorted((data_root / "rulesets").glob("*.json")):
        try:
            with ruleset_path.open("r", encoding="utf-8") as handle:
                json.load(handle)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"invalid JSON in {ruleset_path}: {exc}")

    _check_policy_examples(policy, errors)
    _check_release_pattern_drift(root, data_root, policy, errors)
    _check_workflow_yaml(root, errors)
    _check_template_references(root, errors)
    _check_release_workflow_contract(root, errors)
    _check_baseline_settings_drift(root, policy, errors)
    _check_baseline_settings_keys(root, errors)
    _check_core_agnosticism(root / "aviato" / "core", root / DENYLIST_FILE.relative_to(REPO_ROOT), errors)
    _check_action_pins(root, errors)
    _check_template_scaffold_parity(root, errors)
    _check_scaffold_workflow_yaml(root, errors)
    _check_monotonic_alias_parity(root, errors)

    return errors
