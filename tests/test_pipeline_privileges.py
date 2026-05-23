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


@pytest.mark.parametrize("pipeline,workflow", PIPELINE_WORKFLOWS.items())
def test_pipeline_privileges_match_workflow_permissions(pipeline: str, workflow: str) -> None:
    module = Registry(MODULE_SOURCE_ROOT).pipeline_module(pipeline)
    assert module is not None

    perms = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / workflow).read_text())["permissions"]
    workflow_privs = {f"{key}: {value}" for key, value in perms.items()}
    assert set(module.privileges) == workflow_privs, (
        f"{pipeline} module privileges {set(module.privileges)} != {workflow} permissions {workflow_privs}"
    )


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
    assert set(module.secrets) == set(call_secrets), (
        f"{pipeline} module secrets {set(module.secrets)} != {workflow} workflow_call.secrets {set(call_secrets)}"
    )
