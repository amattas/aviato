from __future__ import annotations

import pytest
import yaml

from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT, REPO_ROOT

# Pipeline module name -> the reusable workflow whose permissions it must mirror (§11.3/§8.9).
PIPELINE_WORKFLOWS = {
    "security-baseline": "reusable-security-baseline.yml",
    "release-gate": "reusable-release-gate.yml",
    "release": "reusable-release.yml",
    "common-lint": "reusable-common-lint.yml",
    "python-verify": "reusable-python-ci.yml",
    "node-verify": "reusable-node-ci.yml",
    "swift-verify": "reusable-swift-ci.yml",
    "pypi-publish": "reusable-pypi-publish.yml",
    "ghcr-publish": "reusable-docker-ghcr.yml",
    "docs-pages": "reusable-docs-pages.yml",
    "app-store-connect": "reusable-app-store-connect.yml",
}

# The release module also owns the caller-side dispatch status bridge. Its token is
# isolated to that no-code job, so this privilege does not belong on reusable-release.
CALLER_ONLY_PRIVILEGES = {
    "release": {"statuses: write"},
    "pypi-publish": {"id-token: write", "attestations: write"},
}


def test_docs_pages_privilege_union_includes_isolated_pages_deployer() -> None:
    module = Registry(MODULE_SOURCE_ROOT).pipeline_module("docs-pages")
    assert module is not None
    assert set(module.privileges) == {
        "contents: read",
        "contents: write",
        "pages: read",
        "pages: write",
        "id-token: write",
    }


def _workflow_privileges(wf: dict) -> set[str]:
    """The UNION of a workflow's top-level + per-job ``permissions`` (§8.9). A workflow may scope
    permissions PER JOB — e.g. docs-pages runs the consumer build under contents:read and deploys under
    id-token/pages:write in a separate job (C12-W4) — so the module's declared privileges must equal the
    union across the workflow, not just the workflow-level block."""
    privs: set[str] = set()
    top = wf.get("permissions")
    if isinstance(top, dict):
        privs |= {f"{key}: {value}" for key, value in top.items()}
    for job in (wf.get("jobs") or {}).values():
        job_perms = job.get("permissions") if isinstance(job, dict) else None
        if isinstance(job_perms, dict):
            privs |= {f"{key}: {value}" for key, value in job_perms.items()}
    return privs


@pytest.mark.parametrize("pipeline,workflow", PIPELINE_WORKFLOWS.items())
def test_pipeline_privileges_match_workflow_permissions(pipeline: str, workflow: str) -> None:
    module = Registry(MODULE_SOURCE_ROOT).pipeline_module(pipeline)
    assert module is not None

    wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / workflow).read_text())
    workflow_privs = _workflow_privileges(wf) | CALLER_ONLY_PRIVILEGES.get(pipeline, set())
    message = f"{pipeline} module privileges {set(module.privileges)} != {workflow} permissions {workflow_privs}"
    assert set(module.privileges) == workflow_privs, message


@pytest.mark.parametrize("pipeline,workflow", PIPELINE_WORKFLOWS.items())
def test_pipeline_secrets_match_workflow_call_secrets(pipeline: str, workflow: str) -> None:
    # review #25: §14 secret matrix — a pipeline module's declared `secrets` must equal the reusable
    # workflow's `workflow_call.secrets` keys. Previously only privileges were guarded, so the
    # secret list could drift from the workflow undetected (they currently match).
    module = Registry(MODULE_SOURCE_ROOT).pipeline_module(pipeline)
    assert module is not None

    wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / workflow).read_text())
    on_block = wf.get("on") or wf.get(True)  # YAML 1.1 parses the `on:` key as boolean True
    call_secrets = (on_block.get("workflow_call") or {}).get("secrets") or {}
    module_secrets = set(module.secrets)
    workflow_secrets = set(call_secrets)
    message = f"{pipeline} module secrets {module_secrets} != {workflow} workflow_call.secrets {workflow_secrets}"
    assert module_secrets == workflow_secrets, message


def test_pypi_privileges_are_split_across_reusable_builder_and_local_publisher() -> None:
    manifest = yaml.safe_load((MODULE_SOURCE_ROOT / "pipelines.yaml").read_text(encoding="utf-8"))
    pypi = manifest["pypi-publish"]
    reusable = _load_workflow("reusable-pypi-publish.yml")
    caller = _load_rendered_python_library_caller()

    build_privileges = set(pypi["reusable_privileges"])
    publisher_privileges = set(pypi["local_publisher_privileges"])
    assert build_privileges == _workflow_privileges(reusable)
    assert publisher_privileges == _job_privileges(caller["jobs"]["pypi-publish"])
    assert set(pypi["privileges"]) == build_privileges | publisher_privileges


def _load_workflow(name: str) -> dict:
    return yaml.safe_load((REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def _load_rendered_python_library_caller() -> dict:
    from aviato.core.onboarding import resolved_artifacts

    artifacts = resolved_artifacts(
        Registry(MODULE_SOURCE_ROOT),
        "python-library",
        {"distribution-name": "example", "import-name": "example"},
        pin="1",
        docs=False,
    )
    body = next(a.body for a in artifacts if a.output == ".github/workflows/aviato-ci.yml")
    return yaml.safe_load(body)


def _job_privileges(job: dict) -> set[str]:
    return {f"{key}: {value}" for key, value in job["permissions"].items()}
