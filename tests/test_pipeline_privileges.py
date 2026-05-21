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
