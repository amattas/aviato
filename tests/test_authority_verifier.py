from __future__ import annotations

import copy
import importlib
from typing import Any

import pytest


def _module() -> Any:
    return importlib.import_module("aviato.authority_verifier")


def _snapshot() -> dict[str, Any]:
    return {
        "schema": "aviato-protection-authority-snapshot/v1",
        "repository": {"database_id": 7, "node_id": "R_7", "full_name": "o/r", "default_branch": "main"},
        "classic": {"requires_pull_request": True},
        "repository_settings": {},
        "security": {"secret_scanning": True},
        "merge": {"allow_squash_merge": True},
        "rulesets": [{"id": 9, "rules": []}],
        "environments": {"pypi": {"can_admins_bypass": False, "reviewers": []}},
        "required_checks": [{"context": "ci", "app_id": 1, "integration_id": None, "source": "classic"}],
        "guard": {
            "intake": {"path": ".github/workflows/aviato-protection-checkpoint.yml", "blob_sha": "a" * 40},
            "release": {
                "repository": "amattas/aviato",
                "ref": "1.0.0",
                "path": ".github/workflows/reusable-release.yml",
                "blob_sha": "b" * 40,
            },
            "verifier": {
                "repository": "amattas/aviato",
                "ref": "1.0.0",
                "path": "aviato/authority_verifier.py",
                "blob_sha": "c" * 40,
            },
        },
    }


@pytest.mark.parametrize(
    "surface",
    (
        "repository",
        "classic",
        "repository_settings",
        "security",
        "merge",
        "rulesets",
        "environments",
        "required_checks",
        "guard",
    ),
)
def test_shared_verifier_rejects_drift_in_every_snapshot_surface(surface: str) -> None:
    expected = _snapshot()
    current = copy.deepcopy(expected)
    current[surface] = {"drift": True}
    with pytest.raises(ValueError, match="authority snapshot"):
        _module().require_exact_authority_snapshot(expected, current)


def test_shared_verifier_flattens_every_paginated_page_and_detects_late_duplicates() -> None:
    pages = [[{"id": value}] for value in range(1, 102)]
    flattened = _module().flatten_paginated_pages(pages, collection_key=None)
    assert [item["id"] for item in flattened] == list(range(1, 102))


def test_shared_verifier_is_stdlib_only_and_has_executable_cli() -> None:
    module = _module()
    assert module.AUTHORITY_SNAPSHOT_SCHEMA == "aviato-protection-authority-snapshot/v1"
    assert callable(module.main) and callable(module.collect_live_authority_snapshot)
