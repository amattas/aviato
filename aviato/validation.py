from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import yaml

from .core.selfcheck import core_import_violations, denylist_violations, load_denylist
from .paths import DENYLIST_FILE, REPO_ROOT
from .plugins.release_mutations import verify_mutation_inventory
from .policy import (
    default_required_approvals,
    get_path,
    library_repository,
    load_policy,
    load_ruleset_manifest,
    load_yaml,
    release_tag_pattern,
)

REQUIRED_FILES = [
    "aviato/library/policy.yml",
    "aviato/library/rulesets.yml",
    # R3-8: load-bearing data files. Without pipelines.yaml, composition silently goes lenient
    # (drops typed privileges/status-checks, disables the undeclared-pipeline check) and without
    # denylist.txt the §9b agnosticism scan can't run — yet validate() reported no missing file.
    "aviato/library/pipelines.yaml",
    "aviato/library/workflow-envelopes.yaml",
    # §13.3 docs scaffold metadata: the Zensical site config (seed-once) and the
    # managed docs toolchain requirements. Load-bearing — a missing metadata file
    # silently drops the artifact from the docs opt-in scaffold set.
    "aviato/library/scaffold/zensical-config.yaml",
    "aviato/library/scaffold/docs-requirements.yaml",
    "aviato/plugins/denylist.txt",
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
    ".github/aviato.yaml",
    ".github/workflows/aviato-ci.yml",
    ".github/workflows/aviato-drift.yml",
    "templates/profile-python-service.yml",
    "templates/profile-python-library.yml",
    "templates/profile-python-component.yml",
    "templates/profile-node-service.yml",
    "templates/profile-swift-app.yml",
    "templates/consumer-automation.yml",
    ".github/workflows/aviato-protection-checkpoint.yml",
    "templates/consumer-protection-checkpoint.yml",
]

RELEASE_WORKFLOWS = [
    ".github/workflows/reusable-release-gate.yml",
    ".github/workflows/reusable-docker-ghcr.yml",
    ".github/workflows/reusable-pypi-publish.yml",
    ".github/workflows/reusable-docs-pages.yml",
    ".github/workflows/reusable-app-store-connect.yml",
]


def _check_project_version_parity(root: Path, errors: list[str]) -> None:
    pyproject = root / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"could not read project version from pyproject.toml: {exc}")
        return
    project_version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(project_version, str):
        errors.append("pyproject.toml does not define project.version")
        return

    try:
        runtime_metadata_version = metadata.version("aviato")
    except metadata.PackageNotFoundError:
        errors.append("installed Aviato distribution metadata is unavailable; cannot verify runtime version parity")
        return

    from . import __version__

    if project_version != runtime_metadata_version:
        errors.append(
            f"project version {project_version!r} differs from runtime distribution metadata "
            f"{runtime_metadata_version!r}"
        )
    if __version__ != runtime_metadata_version:
        errors.append(
            f"runtime __version__ {__version__!r} differs from runtime distribution metadata "
            f"{runtime_metadata_version!r}"
        )


def _check_policy_examples(policy: dict[str, Any], errors: list[str]) -> None:
    pattern = re.compile(release_tag_pattern(policy))
    examples = policy.get("release", {}).get("examples", {})
    for value in examples.get("valid", []):
        if not pattern.fullmatch(str(value)):
            errors.append(f"policy valid release example does not match tag_pattern: {value}")
    for value in examples.get("invalid", []):
        if pattern.fullmatch(str(value)):
            errors.append(f"policy invalid release example matches tag_pattern: {value}")


def _check_release_pattern_drift(root: Path, data_root: Path, policy: dict[str, Any], errors: list[str]) -> None:
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

    # finding 39: the shared docs resolver post-filters the tag list with the SAME
    # policy grammar. Keep that graph-owned fragment tied to the release policy.
    resolve_fragment = root / "aviato/library/workflow-fragments/docs-resolve.yml"
    if resolve_fragment.is_file() and f"grep -E '{pattern}'" not in resolve_fragment.read_text(encoding="utf-8"):
        errors.append(
            "aviato/library/workflow-fragments/docs-resolve.yml does not embed the policy release tag pattern "
            "in its resolve grep (finding 39)"
        )

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
        # R3-12: a malformed/unreadable ruleset JSON is reported by the dedicated JSON-parse check;
        # don't re-raise here (which would abort validate() with a traceback). Skip + record.
        try:
            raw = json.loads((data_root / item["file"]).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"{item['file']} could not be parsed for pattern-drift check: {exc}")
            continue
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


_REMOTE_WORKFLOW_MARKER = "/.github/workflows/"


def _check_remote_reusable_reference(
    value: str,
    *,
    source: str,
    repository: str,
    workflow_files: set[str],
    errors: list[str],
    reject_main: bool = False,
) -> None:
    """Validate every remote reusable-workflow reference, independent of expected prefix."""
    # Identify the workflow-shaped value BEFORE parsing `@ref`. Matching only an already-valid
    # shape would let a missing/trailing `@` bypass every subsequent identity/file check.
    if value.startswith("./") or _REMOTE_WORKFLOW_MARKER not in value:
        return
    actual_repository, workflow_and_ref = value.split(_REMOTE_WORKFLOW_MARKER, 1)
    workflow_file, separator, ref = workflow_and_ref.partition("@")
    if separator != "@" or not ref.strip() or workflow_and_ref.count("@") != 1:
        errors.append(f"{source} reference {value!r} requires exactly one nonempty @ref")
    if actual_repository != repository:
        errors.append(
            f"{source} references Library repository {actual_repository!r}; policy.yml requires {repository!r}"
        )
    if not workflow_file:
        errors.append(f"{source} does not name a reusable workflow file")
    elif workflow_file not in workflow_files:
        errors.append(f"{source} references missing reusable workflow {workflow_file}")
    if reject_main and ref == "main":
        errors.append(f"{source} advertises @{ref}; template examples must use a placeholder pin")


def _check_reusable_call_contract(root: Path, job: dict[str, Any], *, source: str, errors: list[str]) -> None:
    """Validate a rendered caller's with/secrets keys and native input types."""

    uses = job.get("uses")
    if not isinstance(uses, str) or _REMOTE_WORKFLOW_MARKER not in uses and not uses.startswith("./"):
        return
    workflow_name = uses.split(_REMOTE_WORKFLOW_MARKER, 1)[-1].split("@", 1)[0]
    if uses.startswith("./"):
        workflow_name = Path(uses).name
    target = root / ".github/workflows" / workflow_name
    if not target.is_file():
        return
    document = load_yaml(target)
    on_block = document.get("on") or cast(dict[object, Any], document).get(True) or {}
    call = on_block.get("workflow_call", {}) if isinstance(on_block, dict) else {}
    declared_inputs = call.get("inputs", {}) if isinstance(call, dict) else {}
    declared_secrets = call.get("secrets", {}) if isinstance(call, dict) else {}
    actual_inputs = job.get("with", {}) or {}
    actual_secrets = job.get("secrets", {}) or {}
    if not all(isinstance(value, dict) for value in (declared_inputs, declared_secrets, actual_inputs, actual_secrets)):
        errors.append(f"{source} reusable call contract must use mappings")
        return
    unknown_inputs = sorted(set(actual_inputs) - set(declared_inputs))
    unknown_secrets = sorted(set(actual_secrets) - set(declared_secrets))
    if unknown_inputs:
        errors.append(f"{source} passes undeclared reusable input(s) {unknown_inputs} to {workflow_name}")
    if unknown_secrets:
        errors.append(f"{source} passes undeclared reusable secret(s) {unknown_secrets} to {workflow_name}")
    missing = sorted(
        name
        for name, spec in declared_inputs.items()
        if isinstance(spec, dict) and spec.get("required") is True and name not in actual_inputs
    )
    if missing:
        errors.append(f"{source} omits required reusable input(s) {missing} for {workflow_name}")
    missing_secrets = sorted(
        name
        for name, spec in declared_secrets.items()
        if isinstance(spec, dict) and spec.get("required") is True and name not in actual_secrets
    )
    if missing_secrets:
        errors.append(f"{source} omits required reusable secret(s) {missing_secrets} for {workflow_name}")
    expected_types: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "boolean": bool,
        "number": (int, float),
        "string": str,
    }
    for name, value in actual_inputs.items():
        spec = declared_inputs.get(name)
        declared_type = spec.get("type") if isinstance(spec, dict) else None
        expected = expected_types.get(declared_type) if isinstance(declared_type, str) else None
        expression_typed = isinstance(value, str) and value.strip().startswith("${{") and value.strip().endswith("}}")
        wrong_type = expected is not None and not expression_typed and not isinstance(value, expected)
        if declared_type == "number" and isinstance(value, bool):
            wrong_type = True
        if wrong_type:
            errors.append(
                f"{source} input {name!r} for {workflow_name} has {type(value).__name__}, expected {declared_type}"
            )


def _check_reusable_metadata_contract(
    root: Path,
    job_name: str,
    job: dict[str, Any],
    metadata: Any,
    variables: Mapping[str, Any],
    *,
    source: str,
    errors: list[str],
) -> None:
    uses = job.get("uses")
    if not isinstance(uses, str):
        return
    workflow_name = Path(uses.split("@", 1)[0]).name
    target = root / ".github/workflows" / workflow_name
    if not target.is_file():
        return
    called = load_yaml(target)
    called_jobs = called.get("jobs", {})
    if not isinstance(called_jobs, dict):
        return
    runners: set[str] = set()
    for value in called_jobs.values():
        if isinstance(value, dict) and isinstance(value.get("runs-on"), str):
            runners.add(value["runs-on"])
    if metadata.runner and metadata.runner not in runners:
        errors.append(
            f"{source} job {job_name!r} runner {metadata.runner!r} is not provided by {workflow_name}: "
            f"{sorted(runners)}"
        )
    expected_environment = metadata.environment
    if metadata.environment_input:
        expected_environment = variables.get(metadata.environment_input)
    actual_environment = job.get("environment")
    if actual_environment is None and isinstance(job.get("with"), dict):
        actual_environment = job["with"].get("environment-name")
    if expected_environment is not None and actual_environment != expected_environment:
        errors.append(
            f"{source} job {job_name!r} environment {actual_environment!r} does not match metadata "
            f"{expected_environment!r}"
        )
    if expected_environment is not None and isinstance(job.get("with"), dict) and "environment-name" in job["with"]:
        called_environments = {
            (
                value.get("environment", {}).get("name")
                if isinstance(value.get("environment"), dict)
                else value.get("environment")
            )
            for value in called_jobs.values()
            if isinstance(value, dict) and value.get("environment") is not None
        }
        if "${{ inputs.environment-name }}" not in called_environments:
            errors.append(
                f"{source} passes environment-name to {workflow_name}, but the called workflow does not "
                "consume it as a job environment"
            )
    if metadata.status_check:
        prefix, separator, display = metadata.status_check.partition(" / ")
        called_names: set[str] = set()
        for key, value in called_jobs.items():
            if not isinstance(value, dict):
                continue
            called_name = value.get("name", key)
            if isinstance(called_name, str):
                called_names.add(called_name)
        if separator != " / " or prefix != job_name or display not in called_names:
            errors.append(
                f"{source} job {job_name!r} status check {metadata.status_check!r} is not produced by "
                f"{workflow_name} jobs {sorted(called_names)}"
            )


def _check_template_references(root: Path, repository: str, errors: list[str]) -> None:
    workflow_dir = root / ".github/workflows"
    workflow_files = {path.name for path in _yaml_files(workflow_dir)}

    for path in _yaml_files(root / "templates"):
        data = load_yaml(path)
        for job in _walk_jobs(data):
            value = job.get("uses")
            if not isinstance(value, str):
                continue
            _check_remote_reusable_reference(
                value,
                source=str(path.relative_to(root)),
                repository=repository,
                workflow_files=workflow_files,
                errors=errors,
                reject_main=True,
            )
            _check_reusable_call_contract(root, job, source=str(path.relative_to(root)), errors=errors)


def _check_release_workflow_contract(root: Path, repository: str, errors: list[str]) -> None:
    for rel_path in RELEASE_WORKFLOWS:
        text = (root / rel_path).read_text(encoding="utf-8")
        if "release/*" in text or "release/latest" in text:
            errors.append(f"{rel_path} contains legacy release branch support")
        if f"repository: {repository}" in text:
            errors.append(
                f"{rel_path} checks out Aviato by repository name; this can drift from the pinned workflow ref"
            )
        # Require the OPERATIVE guard (the shell comparison that actually gates publishing
        # on a tag ref), not a bare GITHUB_REF_TYPE mention that could sit in a comment.
        if '"${GITHUB_REF_TYPE}" != "tag"' not in text:
            errors.append(f"{rel_path} does not gate publishing on a tag ref (missing GITHUB_REF_TYPE != tag guard)")


def _check_baseline_settings_drift(root: Path, policy: dict[str, Any], errors: list[str]) -> None:
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
    expected = default_required_approvals(policy)
    if "required_reviews" not in default_branch:
        # R3-11: previously this returned clean when the key was ABSENT, so the Library could
        # delete the baseline approval requirement undetected. The key must EXIST and equal policy.
        errors.append(
            "settings baseline is missing required_reviews; it must exist and equal policy.yml's "
            f"required approvals ({expected})"
        )
        return
    if default_branch.get("required_reviews") != expected:
        errors.append(
            f"settings baseline required_reviews ({default_branch.get('required_reviews')}) differs from "
            f"policy.yml required approvals ({expected})"
        )


def _check_docs_caller_name_parity(root: Path, errors: list[str]) -> None:
    """finding 40: docs callers trigger on their CI caller's workflow DISPLAY NAME.

    ``workflow_run`` matches by name; a Library-side rename of a CI caller body would
    silently kill every consumer's docs deploys (the trigger simply never fires — no
    error anywhere). Pin each pair together.
    """

    from .core.compiler import compile_desired_state
    from .core.composition import resolve_profile
    from .core.registry import Registry

    registry = Registry(root / "aviato/library")
    for profile, variables in _TEMPLATE_EXAMPLE_VARS.items():
        try:
            desired = compile_desired_state(
                registry,
                resolve_profile(registry, profile, docs=True),
                variables,
                pin=TEMPLATE_EXAMPLE_PIN,
                docs=True,
            )
            by_output = {workflow.output_path: workflow.document for workflow in desired.workflows}
            ci_name = by_output[".github/workflows/aviato-ci.yml"]["name"]
            trigger_names = by_output[".github/workflows/aviato-docs.yml"]["on"]["workflow_run"]["workflows"]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{profile} compiled docs caller name parity could not be validated: {exc} (finding 40)")
            continue
        if tuple(trigger_names) != (ci_name,):
            errors.append(
                f"{profile} docs workflow_run trigger {trigger_names!r} != CI display name {ci_name!r} "
                "— a rename silently kills docs deploys (finding 40)"
            )


# finding 41: every unavoidable data/workflow copy of the Library repository is anchored on
# policy.yml. Runtime code reads the policy accessor directly and is deliberately absent here.
# A repo rename/transfer must update all of them together or the sites desync pairwise
# (e.g. scaffolds render the new prefix while the pin-exemption still matches the old).
_INSTALL_URL_COPY_COUNTS = {
    ".github/workflows/reusable-consumer-automation.yml": 1,
    ".github/workflows/reusable-common-lint.yml": 1,
    ".github/workflows/reusable-release.yml": 2,
}
_GITHUB_VCS_INSTALL_RE = re.compile(r"git\+https://github\.com/(?P<repository>[^@\s\"']+)@")


def _check_library_repository_copies(root: Path, policy: dict[str, Any], repository: str, errors: list[str]) -> None:
    """Every static and derived Library-repository binding must match policy.yml."""
    for rel_path, expected_count in _INSTALL_URL_COPY_COUNTS.items():
        path = root / rel_path
        if not path.is_file():
            errors.append(f"{rel_path} missing; cannot verify its Library repository copies (finding 41)")
            continue
        actual = _GITHUB_VCS_INSTALL_RE.findall(path.read_text(encoding="utf-8", errors="replace"))
        if len(actual) != expected_count or any(value != repository for value in actual):
            errors.append(
                f"{rel_path} Library install repositories {actual!r} do not equal {expected_count} "
                f"copies of policy library.repository {repository!r} (finding 41)"
            )

    zizmor_path = root / "aviato/library/zizmor.yml"
    if not zizmor_path.is_file():
        errors.append("aviato/library/zizmor.yml missing; cannot verify its Library repository policy (finding 41)")
    else:
        try:
            zizmor = load_yaml(zizmor_path)
            policies = zizmor["rules"]["unpinned-uses"]["config"]["policies"]
            if not isinstance(policies, dict):
                raise TypeError("policies must be a mapping")
        except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"aviato/library/zizmor.yml repository policies cannot be read: {exc} (finding 41)")
        else:
            expected_policies = {
                "actions/*": "ref-pin",
                "github/*": "ref-pin",
                f"{repository}/*": "ref-pin",
                "*": "hash-pin",
            }
            if policies != expected_policies:
                errors.append(
                    "aviato/library/zizmor.yml unpinned-uses policies must be exactly equal to "
                    f"{expected_policies!r}; got {policies!r} (finding 41)"
                )

    contributing = root / "aviato/library/scaffold/files/contributing.md.txt"
    contributing_binding = "https://github.com/{{ aviato-library-repository }}"
    if contributing.is_file() and contributing.read_text(encoding="utf-8").count(contributing_binding) != 1:
        errors.append(
            "aviato/library/scaffold/files/contributing.md.txt must derive its GitHub link from "
            "aviato-library-repository (finding 41)"
        )

    # Enumerate the runtime bindings as contracts too: a future refactor must not load policy yet
    # accidentally ignore it in the plug-in exemption, CLI locator, generated `uses:`
    # references, or rendered contributing link.
    from .cli import _library_repository
    from .core.onboarding import resolved_artifacts
    from .core.registry import Registry
    from .plugins.actionpins import unpinned_third_party_uses

    mutable_self_ref = f"uses: {repository}/.github/workflows/example.yml@1"
    if unpinned_third_party_uses(mutable_self_ref, library_repository=repository):
        errors.append("action-pin plug-in allowlist does not derive from policy library.repository (finding 41)")

    if _library_repository(policy) != repository:
        errors.append("CLI Library locator does not derive from policy library.repository")

    try:
        artifacts = resolved_artifacts(
            Registry(root / "aviato/library"),
            "python-library",
            _TEMPLATE_EXAMPLE_VARS["python-library"],
            pin=TEMPLATE_EXAMPLE_PIN,
        )
    except Exception as exc:  # noqa: BLE001 - validation reports malformed Library data
        errors.append(f"could not validate rendered Library-repository bindings: {exc}")
    else:
        rendered = {artifact.output: artifact.body for artifact in artifacts}
        callers = [
            body
            for output, body in rendered.items()
            if output.startswith(".github/workflows/") and f"{repository}/.github/workflows/" in body
        ]
        if not callers:
            errors.append(
                f"generated uses references do not derive from policy library.repository {repository!r} (finding 41)"
            )
        contributing_body = rendered.get("CONTRIBUTING.md", "")
        expected_link = f"https://github.com/{repository}"
        if expected_link not in contributing_body:
            errors.append(
                f"rendered CONTRIBUTING.md does not link to policy Library repository {expected_link!r} (finding 41)"
            )


def _check_scaffold_constant_parity(root: Path, errors: list[str]) -> None:
    """finding 43: shared literals maintained in workflow fragments must not desync.

    These have no policy.yml home, so editing a graph fragment must not silently leave
    related fragments behind.
    """
    scaffold_dir = root / "aviato" / "library" / "workflow-fragments"

    def _values(glob: str, regex: str) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for body in sorted(scaffold_dir.glob(glob)):
            hits = re.findall(regex, body.read_text(encoding="utf-8"))
            if hits:
                found[body.name] = hits
        return found

    versions = _values("python-verify.yml", r'python-version:\s*"([^"]+)"')
    if len({v for vs in versions.values() for v in vs}) > 1:
        errors.append(f"python-version differs across workflow fragments: {versions} (finding 43)")

    pins = _values("docs-python-*.yml", r"pydoc-markdown==([0-9.]+)")
    if len({v for vs in pins.values() for v in vs}) > 1:
        errors.append(f"pydoc-markdown pins differ across docs callers: {pins} (finding 43)")

    toolchain_path = root / "aviato/library/docs-toolchain.yaml"
    if not toolchain_path.is_file():
        errors.append("missing docs toolchain pin source: aviato/library/docs-toolchain.yaml")
    else:
        try:
            toolchain = load_yaml(toolchain_path)
            pydoc_pin = str(toolchain["pydoc-markdown"])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"invalid docs toolchain pin source: {exc}")
        else:
            pins = _values("docs-python-*.yml", r"pydoc-markdown==([0-9.]+)")
            actual = {pin for values in pins.values() for pin in values}
            if actual != {pydoc_pin}:
                errors.append(
                    f"pydoc-markdown pins across docs callers {pins} differ from docs-toolchain.yaml "
                    f"({pydoc_pin!r}) (finding 43)"
                )
            expected_requirements = [f"zensical=={toolchain['zensical']}", f"mike @ {toolchain['mike']}"]
            for rel_path in (
                "starter/docs-site/requirements.txt",
                "aviato/library/scaffold/files/docs-requirements.txt.txt",
            ):
                path = root / rel_path
                if not path.is_file():
                    errors.append(f"missing docs toolchain generated output: {rel_path}")
                    continue
                requirements = [
                    line.split("#", 1)[0].strip()
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.split("#", 1)[0].strip()
                ]
                if requirements != expected_requirements:
                    errors.append(
                        f"docs toolchain pins differ in {rel_path} from aviato/library/docs-toolchain.yaml: "
                        f"actual={requirements}, expected={expected_requirements} (finding 43)"
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
    declared = (
        set(settings.get("default_branch", {}))
        | set(settings.get("security", {}))
        | set(settings.get("repository", {}))
    )
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


def _check_action_pins(root: Path, repository: str, errors: list[str]) -> None:
    """§11.3: third-party actions/tools invoked by any pipeline are pinned by digest."""
    from .plugins.actionpins import action_pin_violations

    for violation in action_pin_violations(
        root,
        policy_root=root / "aviato/library",
        library_repository=repository,
    ):
        errors.append(f"unpinned third-party action/tool (§11.3): {violation}")


# The documented copyable caller templates are COMPILED from the authoritative pipeline
# graph with these example variables — they are not a hand-maintained second copy.
# The parity check below fails if they drift, so editing the graph forces a regenerate
# (scripts/regen-templates.py).
_TEMPLATE_EXAMPLE_VARS: dict[str, dict[str, str]] = {
    "python-library": {"distribution-name": "your-distribution", "import-name": "your_package"},
    # A container service declares no packaging/image vars — the GHCR image defaults to the repo
    # slug (R4-2, mirrors node-service) and it ships no wheel/import name (§13.2).
    "python-service": {},
    "python-component": {"distribution-name": "your-distribution", "import-name": "your_package"},
    "node-service": {"project-name": "your-app", "language-variant": "typescript"},
    "swift-app": {
        "product-scheme": "App",
        "workspace": "App.xcworkspace",
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
TEMPLATE_EXAMPLE_PIN = "EXAMPLE_PIN"


def _rendered_caller(root: Path, profile: str, output: str) -> str | None:
    from .core.onboarding import resolved_artifacts
    from .core.registry import Registry

    registry = Registry(root / "aviato" / "library")
    artifacts = resolved_artifacts(
        registry, profile, _TEMPLATE_EXAMPLE_VARS[profile], pin=TEMPLATE_EXAMPLE_PIN, docs=False
    )
    return next((a.body for a in artifacts if a.output == output), None)


def _check_scaffold_workflow_yaml(root: Path, repository: str, errors: list[str]) -> None:
    """Each graph-compiled workflow body must be valid YAML (§16).

    One-job fragments carry ``{{ var }}`` placeholders, so validate each profile's
    compiled callers (docs off AND on) with example variables before consumers receive them.
    """
    from .core.composition import resolve_profile
    from .core.onboarding import resolved_artifacts
    from .core.registry import Registry
    from .core.variables import resolve_declared_variables

    # review #25: docs workflows (rendered only with docs=True) have NO committed template, so
    # _check_template_references never validates their `uses:` targets. Verify here that every
    # reusable-workflow ref in a rendered caller resolves to a workflow that actually exists, so a
    # renamed/deleted reusable workflow can't ship a broken caller to consumers undetected.
    workflow_files = {path.name for path in _yaml_files(root / ".github/workflows")}
    registry = Registry(root / "aviato" / "library")
    for profile, example_vars in _TEMPLATE_EXAMPLE_VARS.items():
        for docs in (False, True):
            try:
                resolved = resolve_profile(registry, profile, docs=docs)
                exact_variables = resolve_declared_variables(resolved.variables, example_vars)
                metadata = {
                    (registry.workflow_envelope(module.envelope or "").output_path, job.name): job
                    for module in resolved.pipeline_modules
                    for job in module.jobs
                }
                artifacts = resolved_artifacts(registry, profile, example_vars, pin=TEMPLATE_EXAMPLE_PIN, docs=docs)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"workflow graph render failed for {profile!r} (docs={docs}): {exc}")
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
                        f"rendered graph workflow {artifact.output} ({profile!r}, docs={docs}) is invalid YAML: {exc}"
                    )
                    continue
                jobs = doc.get("jobs", {}) if isinstance(doc, dict) else {}
                for job_name, job in jobs.items():
                    if not isinstance(job_name, str) or not isinstance(job, dict):
                        continue
                    uses = job.get("uses")
                    if isinstance(uses, str):
                        _check_remote_reusable_reference(
                            uses,
                            source=f"rendered graph workflow {artifact.output} ({profile!r}, docs={docs})",
                            repository=repository,
                            workflow_files=workflow_files,
                            errors=errors,
                        )
                        _check_reusable_call_contract(
                            root,
                            job,
                            source=f"rendered graph workflow {artifact.output} ({profile!r}, docs={docs})",
                            errors=errors,
                        )
                        metadata_key = (artifact.output, job_name)
                        if metadata_key in metadata:
                            _check_reusable_metadata_contract(
                                root,
                                job_name,
                                job,
                                metadata[metadata_key],
                                exact_variables,
                                source=f"rendered graph workflow {artifact.output} ({profile!r}, docs={docs})",
                                errors=errors,
                            )


def _check_template_scaffold_parity(root: Path, errors: list[str]) -> None:
    """Documented caller templates must equal graph-compiled output (no drift)."""
    checks = [(p, f, ".github/workflows/aviato-ci.yml") for p, f in _PROFILE_TEMPLATE_FILES.items()]
    checks.append(("python-library", "templates/consumer-automation.yml", ".github/workflows/aviato-drift.yml"))
    checks.append(
        (
            "python-library",
            "templates/consumer-protection-checkpoint.yml",
            ".github/workflows/aviato-protection-checkpoint.yml",
        )
    )
    for profile, rel_path, output in checks:
        path = root / rel_path
        if not path.exists():
            continue  # absence is already reported by the REQUIRED_FILES check
        try:
            expected = _rendered_caller(root, profile, output)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel_path}: workflow graph could not be rendered: {exc}")
            continue
        if expected is None:
            errors.append(f"{rel_path}: profile {profile!r} no longer produces {output}")
        elif path.read_text(encoding="utf-8") != expected:
            errors.append(
                f"{rel_path} is stale: it does not match the graph-compiled caller for "
                f"{profile!r}. Regenerate with scripts/regen-templates.py."
            )


def _check_status_bridge_contexts(root: Path, errors: list[str]) -> None:
    """Keep caller bridge contexts derived from composed pipeline module data.

    Release-branch CI is started with ``workflow_dispatch``. GitHub reports those
    checks against the workflow run rather than the release PR, so each caller has a
    no-code bridge that publishes the same required contexts to ``github.sha``. The
    contexts must come from ``PipelineModule.status_check``; a copied string in one
    caller must never silently diverge from branch protection.
    """
    from .core.composition import resolve_profile
    from .core.registry import Registry

    registry = Registry(root / "aviato" / "library")
    for profile in _PROFILE_TEMPLATE_FILES:
        source = f"compiled {profile} release status bridge"
        try:
            expected = {
                module.status_check
                for module in resolve_profile(registry, profile).pipeline_modules
                if module.status_check is not None
            }
            rendered = _rendered_caller(root, profile, ".github/workflows/aviato-ci.yml")
            document = yaml.safe_load(rendered) if rendered is not None else None
            bridge = document["jobs"]["status-bridge"] if isinstance(document, dict) else None
            steps = bridge.get("steps", []) if isinstance(bridge, dict) else []
            actual = [
                context
                for step in steps
                if isinstance(step, dict)
                and isinstance(step.get("env"), dict)
                and isinstance((context := step["env"].get("STATUS_CONTEXT")), str)
            ]
        except Exception as exc:  # noqa: BLE001 - validation reports malformed source data
            errors.append(f"{source} status bridge could not be validated: {exc}")
            continue
        if set(actual) != expected or len(actual) != len(expected):
            errors.append(
                f"{source} status bridge contexts {sorted(actual)} do not match resolved "
                f"PipelineModule.status_check contexts; expected {sorted(expected)}"
            )


def _check_library_bootstrap(root: Path, repository: str, errors: list[str]) -> None:
    """The Library's own managed artifacts must bootstrap through local workflow refs (§5.10)."""
    from .core.declaration import load_declaration
    from .core.onboarding import resolved_artifacts
    from .core.pathguard import confined_target
    from .core.registry import Registry
    from .core.scaffold import ScaffoldItem, read_sidecar, render_managed

    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.exists():
        return  # absence is already reported by REQUIRED_FILES
    try:
        declaration = load_declaration(declaration_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f".github/aviato.yaml is invalid: {exc}")
        return
    if not declaration.bootstrap:
        errors.append(".github/aviato.yaml must declare bootstrap: true for the Library self-reference path (§5.10)")
        return

    registry = Registry(root / "aviato" / "library")
    try:
        artifacts = resolved_artifacts(
            registry,
            declaration.profile,
            declaration.variables,
            pin=declaration.version,
            docs=declaration.docs,
            bootstrap=True,
            overrides=declaration.overrides,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Library bootstrap scaffold render failed: {exc}")
        return

    expected = {}
    expected_seeds: set[str] = set()
    for artifact in artifacts:
        if artifact.seed_once:
            expected_seeds.add(artifact.output)
            continue
        item = ScaffoldItem(
            output=artifact.output,
            body=artifact.body,
            comment=artifact.comment,
            input_hash=artifact.input_hash,
        )
        expected[artifact.output] = render_managed(item, profile=declaration.profile, version=declaration.version)
    if not expected:
        errors.append("Library bootstrap declaration resolves no managed artifacts (§5.10)")
        return
    for rel_path, body in expected.items():
        path = root / rel_path
        if not path.exists():
            errors.append(f"missing Library bootstrap managed artifact: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        if text != body:
            errors.append(f"{rel_path} is stale: it does not match the rendered Library bootstrap artifact (§5.10)")
        if f"{repository}/.github/workflows/" in text:
            errors.append(f"{rel_path} uses a released Aviato ref in bootstrap; use local workflow refs (§5.10)")

    sidecar = read_sidecar(root)
    if not expected_seeds and sidecar.status != "missing":
        errors.append("Library seed sidecar exists but the declaration resolves no seed outputs")
    elif expected_seeds and sidecar.status != "ok":
        errors.append(f"Library seed sidecar is {sidecar.status}; explicitly rebaseline current seed outputs")
    elif expected_seeds:
        missing_records = sorted(expected_seeds - sidecar.hashes.keys())
        obsolete_records = sorted(sidecar.hashes.keys() - expected_seeds)
        if missing_records or obsolete_records:
            errors.append(
                "Library seed sidecar does not exactly match resolved seed outputs: "
                f"missing={missing_records}, obsolete={obsolete_records}"
            )
    for rel_path in sorted(expected_seeds):
        if not confined_target(root, rel_path, operation="validate Library seed output").is_file():
            errors.append(f"missing Library bootstrap seed artifact: {rel_path}")


# Workflows that embed an inline `highest.py` reimplementation of the §8.14/§13.2 monotonic
# alias guard (kept inline to avoid a self-reference install in the deploy job). The parity
# check below proves each inline copy still agrees with aviato.core.versioning.is_highest, so a
# silent divergence (e.g. prerelease ranking) cannot let an older release move `latest`/docs back.
_MONOTONIC_ALIAS_WORKFLOWS = [
    ".github/workflows/reusable-docker-ghcr.yml",
    ".github/workflows/reusable-docs-pages.yml",
    # The starter kit's copyable docs caller embeds the same hand-copied comparator (as a
    # `<<'PY'` heredoc), so it joins the parity battery — a drifted kit copy would let an
    # older release move the `latest` alias backward just as a workflow copy would.
    "starter/docs-site/docs.yml",
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
    """Return the body of the monotonic-GUARD ``<<'PY' ... PY`` heredoc in a step ``run``, or None.

    R5-11: select the heredoc that IS the guard (its body prints ``true``/``false`` — the is_highest
    comparator's output), not merely the FIRST ``<<'PY'`` in the run. Otherwise an unrelated earlier
    heredoc would make the parity check compare the wrong snippet and miss a drifted/removed guard.
    The YAML loader already dedents the block, so captured lines are valid Python.
    """
    lines = run_text.splitlines()
    heredocs: list[str] = []
    i = 0
    while i < len(lines):
        if "<<'PY'" in lines[i]:
            body: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != "PY":
                body.append(lines[i])
                i += 1
            heredocs.append("\n".join(body))
        i += 1
    # Only the guard is relevant. Other bounded inline Python (for example the
    # checkpoint-bound authority verifier bootstrap) must not be executed as a
    # version comparator merely because it is the sole heredoc in its step.
    guard = [h for h in heredocs if "true" in h and "false" in h]
    return guard[0] if guard else None


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
            try:
                result = subprocess.run(
                    [sys.executable, "-c", snippet, candidate],
                    input="\n".join(existing),
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except subprocess.TimeoutExpired:
                errors.append(
                    f"{rel_path}: monotonic-alias parity snippet timed out after 5 seconds; "
                    "inspect the inline highest.py guard for blocking or non-terminating code."
                )
                break
            inline = result.stdout.strip()
            expected = "true" if is_highest(candidate, existing) else "false"
            if inline != expected:
                errors.append(
                    f"{rel_path}: inline highest.py disagrees with core is_highest for "
                    f"candidate={candidate!r} existing={existing!r} (inline={inline!r}, "
                    f"core={expected!r}); the copy has drifted from aviato.core.versioning."
                )


def _permission_set(block: object) -> set[str]:
    if not isinstance(block, dict):
        return set()
    return {f"{key}: {value}" for key, value in block.items()}


def _check_pypi_privilege_split(root: Path, errors: list[str]) -> None:
    """Keep PyPI build and trusted-publisher privileges bound to their workflow identities."""
    manifest = load_yaml(root / "aviato" / "library" / "pipelines.yaml")
    module = manifest.get("pypi-publish")
    if not isinstance(module, dict):
        return

    reusable_declared = set(module.get("reusable_privileges") or ())
    publisher_declared = set(module.get("local_publisher_privileges") or ())
    union_declared = set(module.get("privileges") or ())
    reusable = load_yaml(root / ".github" / "workflows" / "reusable-pypi-publish.yml")
    reusable_actual = _permission_set(reusable.get("permissions"))
    try:
        caller_body = _rendered_caller(root, "python-library", ".github/workflows/aviato-ci.yml")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"PyPI rendered consumer publisher caller could not be validated: {exc}")
        return
    caller = yaml.safe_load(caller_body) if caller_body is not None else {}
    publish_job = (caller.get("jobs") or {}).get("pypi-publish") if isinstance(caller, dict) else None
    publisher_actual = _permission_set(publish_job.get("permissions") if isinstance(publish_job, dict) else None)

    if reusable_declared != reusable_actual:
        errors.append(
            "PyPI reusable build privileges do not match reusable-pypi-publish.yml "
            f"(declared={sorted(reusable_declared)}, actual={sorted(reusable_actual)})"
        )
    if publisher_declared != publisher_actual:
        errors.append(
            "PyPI local publisher privileges do not match the rendered consumer publisher job "
            f"(declared={sorted(publisher_declared)}, actual={sorted(publisher_actual)})"
        )
    if union_declared != reusable_declared | publisher_declared:
        errors.append("PyPI pipeline privileges must equal reusable plus local publisher privileges")


def _check_hosted_mutation_inventory(root: Path, errors: list[str]) -> None:
    try:
        body = _rendered_caller(root, "python-library", ".github/workflows/aviato-ci.yml")
        rendered = yaml.safe_load(body) if body is not None else {}
        if not isinstance(rendered, dict):
            raise ValueError("rendered Python workflow is not a mapping")
        inventory_errors = verify_mutation_inventory(root / ".github" / "workflows", rendered)
    except Exception as exc:  # noqa: BLE001 - validation reports a single actionable error
        errors.append(f"hosted mutation inventory could not be validated: {exc}")
        return
    errors.extend(f"hosted mutation inventory: {error}" for error in inventory_errors)


def validate(root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []

    _check_project_version_parity(root, errors)

    for rel_path in REQUIRED_FILES:
        if not (root / rel_path).exists():
            errors.append(f"missing required file: {rel_path}")

    # Policy + ruleset DATA now lives in the package (`aviato/library`) so it ships in the wheel
    # (§5.6/§11.3); validate the IN-REPO copy under the operated root.
    data_root = root / "aviato" / "library"
    try:
        policy = load_policy(data_root)
        repository = library_repository(policy)
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
    _check_template_references(root, repository, errors)
    _check_release_workflow_contract(root, repository, errors)
    _check_baseline_settings_drift(root, policy, errors)
    _check_baseline_settings_keys(root, errors)
    _check_docs_caller_name_parity(root, errors)
    _check_library_repository_copies(root, policy, repository, errors)
    _check_scaffold_constant_parity(root, errors)
    _check_core_agnosticism(root / "aviato" / "core", root / DENYLIST_FILE.relative_to(REPO_ROOT), errors)
    _check_action_pins(root, repository, errors)
    _check_template_scaffold_parity(root, errors)
    _check_status_bridge_contexts(root, errors)
    _check_pypi_privilege_split(root, errors)
    _check_scaffold_workflow_yaml(root, repository, errors)
    _check_library_bootstrap(root, repository, errors)
    _check_monotonic_alias_parity(root, errors)
    _check_hosted_mutation_inventory(root, errors)

    return errors
