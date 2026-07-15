"""Bijective inventory of hosted mutations and OIDC attestations."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import shlex
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

FULL_VERIFIER_CONTRACT = "aviato-full-authority-verifier/v1"
OIDC_ACTIONS = frozenset(
    {
        "actions/attest-build-provenance",
        "actions/attest-sbom",
        "actions/deploy-pages",
        "pypa/gh-action-pypi-publish",
    }
)
CANONICAL_VERIFIER_RUN_SHA256 = {
    "aviato-verify-app-archive-attestation": "f8112a52550b2393624b054c7de393de06535eb2570680e4d55da20132f3b258",
    "aviato-verify-docs-push": "e2d12ded6f222e8ed92cb5195b4bd11d26406eb776e909c42aa721b9153864d8",
    "aviato-verify-image-attestation": "f8112a52550b2393624b054c7de393de06535eb2570680e4d55da20132f3b258",
    "aviato-verify-pages-deploy": "db8b8c4dc67b220b6cc067a6b572a17c15915d9284b65970a73660b065609f51",
    "aviato-verify-pypi-alternate": "f8112a52550b2393624b054c7de393de06535eb2570680e4d55da20132f3b258",
    "aviato-verify-pypi-provenance": "f8112a52550b2393624b054c7de393de06535eb2570680e4d55da20132f3b258",
    "aviato-verify-pypi-publish": "f8112a52550b2393624b054c7de393de06535eb2570680e4d55da20132f3b258",
    "aviato-verify-pypi-sbom": "f8112a52550b2393624b054c7de393de06535eb2570680e4d55da20132f3b258",
}
ActionKind = Literal["shell", "action", "oidc-attestation"]


@dataclass(frozen=True)
class HostedMutation:
    workflow: str
    job: str
    step: str
    marker: str
    kind: ActionKind = "shell"
    guard_call: str | None = None
    verifier_step_id: str | None = None
    boundary: Literal[
        "same-step",
        "preceding-verifier",
        "job-authority",
        "authority-job",
        "isolated-attestation",
        "status-bridge",
        "fixed-artifact-attestation",
    ] = "same-step"

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (self.workflow, self.job, self.step, self.kind, self.marker)


HOSTED_MUTATIONS: tuple[HostedMutation, ...] = (
    HostedMutation(
        "rendered-python",
        "pypi-publish",
        "Attest build provenance",
        "actions/attest-build-provenance",
        "oidc-attestation",
        verifier_step_id="aviato-verify-pypi-provenance",
        boundary="job-authority",
    ),
    HostedMutation(
        "rendered-python",
        "pypi-publish",
        "Attest SBOM",
        "actions/attest-sbom",
        "oidc-attestation",
        verifier_step_id="aviato-verify-pypi-sbom",
        boundary="job-authority",
    ),
    HostedMutation(
        "rendered-python",
        "pypi-publish",
        "Publish distributions",
        "pypa/gh-action-pypi-publish",
        "action",
        verifier_step_id="aviato-verify-pypi-publish",
        boundary="preceding-verifier",
    ),
    HostedMutation(
        "rendered-python", "status-bridge", "Publish verify status", "statuses/${GITHUB_SHA}", boundary="status-bridge"
    ),
    HostedMutation(
        "rendered-python",
        "status-bridge",
        "Publish security baseline status",
        "statuses/${GITHUB_SHA}",
        boundary="status-bridge",
    ),
    HostedMutation(
        "rendered-python",
        "status-bridge",
        "Publish common lint status",
        "statuses/${GITHUB_SHA}",
        boundary="status-bridge",
    ),
    HostedMutation(
        "rendered-python",
        "pypi-publish",
        "Publish distributions to alternate repository",
        "pypa/gh-action-pypi-publish",
        "action",
        verifier_step_id="aviato-verify-pypi-alternate",
        boundary="preceding-verifier",
    ),
    HostedMutation(
        "aviato-ci.yml",
        "pypi-publish",
        "Attest build provenance",
        "actions/attest-build-provenance",
        "oidc-attestation",
        verifier_step_id="aviato-verify-pypi-provenance",
        boundary="job-authority",
    ),
    HostedMutation(
        "aviato-ci.yml",
        "pypi-publish",
        "Attest SBOM",
        "actions/attest-sbom",
        "oidc-attestation",
        verifier_step_id="aviato-verify-pypi-sbom",
        boundary="job-authority",
    ),
    HostedMutation(
        "aviato-ci.yml",
        "pypi-publish",
        "Publish distributions",
        "pypa/gh-action-pypi-publish",
        "action",
        verifier_step_id="aviato-verify-pypi-publish",
        boundary="preceding-verifier",
    ),
    HostedMutation(
        "aviato-ci.yml", "status-bridge", "Publish verify status", "statuses/${GITHUB_SHA}", boundary="status-bridge"
    ),
    HostedMutation(
        "aviato-ci.yml",
        "status-bridge",
        "Publish security baseline status",
        "statuses/${GITHUB_SHA}",
        boundary="status-bridge",
    ),
    HostedMutation(
        "aviato-ci.yml",
        "status-bridge",
        "Publish common lint status",
        "statuses/${GITHUB_SHA}",
        boundary="status-bridge",
    ),
    HostedMutation(
        "aviato-ci.yml",
        "pypi-publish",
        "Publish distributions to alternate repository",
        "pypa/gh-action-pypi-publish",
        "action",
        verifier_step_id="aviato-verify-pypi-alternate",
        boundary="preceding-verifier",
    ),
    HostedMutation(
        "aviato-protection-checkpoint.yml",
        "attest",
        "Attest fixed verified artifact",
        "actions/attest-build-provenance",
        "oidc-attestation",
        boundary="fixed-artifact-attestation",
    ),
    HostedMutation(
        "reusable-docker-ghcr.yml",
        "docker",
        "Push scanned digests and assemble release tag (C12-W3)",
        "skopeo copy",
        guard_call="aviato_verify_authority",
    ),
    HostedMutation(
        "reusable-docker-ghcr.yml",
        "docker",
        "Push scanned digests and assemble release tag (C12-W3)",
        'imagetools create -t "${IMAGE}:${TAG}"',
        guard_call="aviato_verify_authority",
    ),
    HostedMutation(
        "reusable-docker-ghcr.yml",
        "attest-image",
        "Attest published image provenance",
        "actions/attest-build-provenance",
        "oidc-attestation",
        verifier_step_id="aviato-verify-image-attestation",
        boundary="preceding-verifier",
    ),
    HostedMutation(
        "reusable-docker-ghcr.yml",
        "docker",
        "Tag and push latest (monotonic guard)",
        'imagetools create -t "${IMAGE}:latest"',
        guard_call="aviato_verify_authority",
    ),
    HostedMutation(
        "reusable-app-store-connect.yml",
        "attest-unsigned",
        "Attest unsigned archive provenance",
        "actions/attest-build-provenance",
        "oidc-attestation",
        verifier_step_id="aviato-verify-app-archive-attestation",
        boundary="isolated-attestation",
    ),
    HostedMutation(
        "reusable-app-store-connect.yml",
        "app-store-connect",
        "Upload to App Store Connect",
        "xcrun altool --upload-app",
        guard_call="aviato_verify_authority",
    ),
    HostedMutation(
        "reusable-app-store-connect.yml",
        "app-store-connect",
        "Submit for review (built-in)",
        "fastlane deliver",
        guard_call="aviato_verify_authority",
    ),
    HostedMutation(
        "reusable-app-store-connect.yml",
        "release-evidence",
        "Persist receipt asset and release-note evidence",
        "gh release upload",
        guard_call="aviato_verify_authority",
    ),
    HostedMutation(
        "reusable-app-store-connect.yml",
        "release-evidence",
        "Persist receipt asset and release-note evidence",
        "gh release edit",
    ),
    HostedMutation(
        "reusable-docs-pages.yml", "push", "Fast-forward docs branch", "git push", boundary="preceding-verifier"
    ),
    HostedMutation(
        "reusable-docs-pages.yml",
        "deploy",
        "Deploy GitHub Pages",
        "actions/deploy-pages",
        "action",
        verifier_step_id="aviato-verify-pages-deploy",
        boundary="preceding-verifier",
    ),
    HostedMutation("reusable-release.yml", "release", "Propose release PR", "git push", boundary="authority-job"),
    HostedMutation(
        "reusable-release.yml",
        "release",
        "Verify checkpoint and perform closed promotion",
        'git/refs" -f ref="refs/tags/${NEXT}',
        guard_call="aviato_verify_authority",
    ),
    HostedMutation(
        "reusable-release.yml",
        "release",
        "Verify checkpoint and perform closed promotion",
        "git/refs/tags/${major}",
        guard_call="aviato_verify_authority",
    ),
    HostedMutation(
        "reusable-release.yml",
        "release",
        "Verify checkpoint and perform closed promotion",
        'git/refs" -f ref="refs/tags/${major}',
        guard_call="aviato_verify_authority",
    ),
    HostedMutation(
        "reusable-release.yml",
        "release",
        "Verify checkpoint and perform closed promotion",
        'repos/${GITHUB_REPOSITORY}/releases"',
        guard_call="aviato_verify_authority",
    ),
)

_ACTION_KINDS: dict[str, ActionKind] = {
    "actions/attest-build-provenance": "oidc-attestation",
    "actions/attest-sbom": "oidc-attestation",
    "pypa/gh-action-pypi-publish": "action",
    "actions/deploy-pages": "action",
}
_GITHUB_API_MARKERS = (
    'git/refs" -f ref="refs/tags/${NEXT}',
    "git/refs/tags/${major}",
    'git/refs" -f ref="refs/tags/${major}',
    'repos/${GITHUB_REPOSITORY}/releases"',
    "statuses/${GITHUB_SHA}",
)


@dataclass(frozen=True)
class PrivilegedJobContract:
    workflow: str
    job: str
    trust_edge: str
    workflow_sha256: str
    permissions: tuple[tuple[str, str], ...]
    workflow_env_keys: tuple[str, ...]
    workflow_env_sha256: str
    workflow_defaults_sha256: str
    needs_sha256: str
    outputs_sha256: str
    job_env_keys: tuple[str, ...]
    job_env_sha256: str
    job_defaults_sha256: str
    container_sha256: str
    services_sha256: str
    step_order: tuple[tuple[str, str], ...]
    step_uses: tuple[str, ...]
    step_run_sha256: tuple[str, ...]
    step_shells: tuple[str, ...]
    step_env_keys: tuple[tuple[str, ...], ...]
    step_env_sha256: tuple[str, ...]
    job_sha256: str


_PRIVILEGED_MANIFEST_PATH = Path(__file__).parents[1] / "library" / "privileged-execution-manifest.json"
_PRIVILEGED_REVIEW_POLICY_REL = Path("aviato/library/privileged-review-policy.json")
_PRIVILEGED_REVIEW_RECORD_REL = Path(".github/aviato-privileged-review.json")
_PRIVILEGED_REVIEW_ATTESTATION_NAME = "privileged-review-attestation.json"
_PRIVILEGED_CODEOWNERS_REL = Path(".github/CODEOWNERS")
_PRIVILEGED_RULESET_REL = Path("aviato/library/rulesets/protect-default-branch.json")
_PRIVILEGED_PROTECTED_PATHS = (
    "/.github/workflows/",
    "/.github/CODEOWNERS",
    "/.github/aviato-privileged-review.json",
    "/.github/aviato.yaml",
    "/aviato/library/privileged-execution-manifest.json",
    "/aviato/library/privileged-review-policy.json",
    "/aviato/library/policy.yml",
    "/aviato/library/rulesets/protect-default-branch.json",
    "/aviato/cli.py",
    "/aviato/plugins/privileged_review.py",
    "/aviato/plugins/approved_release.py",
    "/aviato/plugins/release_mutations.py",
    "/MANIFEST.in",
    "/pyproject.toml",
    "/scripts/regen-privileged-execution-manifest.py",
    "/scripts/build-approved-release.py",
)
_PRIVILEGED_POLICY_KEYS = {
    "schema_version",
    "minimum_approvals",
    "require_non_author",
    "require_code_owner_review",
    "require_last_push_approval",
    "dismiss_stale_reviews_on_push",
    "maximum_attestation_ttl_seconds",
    "required_status_checks",
    "trusted_issuer",
    "trusted_environment",
    "trusted_workflow_path",
    "trusted_signing_keys",
    "revoked_key_versions",
    "reviewer_database_ids",
    "team_database_ids",
    "protected_paths",
}
_PRIVILEGED_REVIEW_RECORD_KEYS = {
    "schema_version",
    "status",
    "lifecycle",
    "activation_request_id",
    "activation_nonce",
    "author_database_id",
    "approvals",
    "candidate_manifest_sha256",
    "policy_sha256",
    "codeowners_sha256",
    "manual_prerequisites",
}


def _privileged_policy_errors(policy: object, *, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict) or set(policy) != _PRIVILEGED_POLICY_KEYS:
        return [f"{label} policy keys/schema are not exact"]
    if policy.get("schema_version") != 2:
        errors.append(f"{label} policy schema_version is unsupported")
    minimum = policy.get("minimum_approvals")
    ttl = policy.get("maximum_attestation_ttl_seconds")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 2:
        errors.append(f"{label} policy minimum approvals are invalid")
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 31_536_000 <= ttl <= 63_072_000:
        errors.append(f"{label} policy attestation TTL is invalid")
    for flag in (
        "require_non_author",
        "require_code_owner_review",
        "require_last_push_approval",
        "dismiss_stale_reviews_on_push",
    ):
        if policy.get(flag) is not True:
            errors.append(f"{label} policy must require {flag}")

    def canonical_positive_ids(name: str) -> list[int]:
        value = policy.get(name)
        if (
            not isinstance(value, list)
            or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value)
            or value != sorted(set(value))
        ):
            errors.append(f"{label} policy {name} must be canonical unique positive IDs")
            return []
        return value

    canonical_positive_ids("reviewer_database_ids")
    canonical_positive_ids("team_database_ids")
    canonical_positive_ids("revoked_key_versions")
    protected = policy.get("protected_paths")
    if (
        not isinstance(protected, list)
        or any(
            not isinstance(path, str) or not path.startswith("/") or ".." in Path(path).parts or "//" in path
            for path in protected
        )
        or protected != sorted(set(protected))
    ):
        errors.append(f"{label} policy protected paths are not canonical unique absolute paths")
    checks = policy.get("required_status_checks")
    if (
        not isinstance(checks, list)
        or len(checks) < 2
        or any(not isinstance(check, str) or not check or check.strip() != check for check in checks)
        or checks != sorted(set(checks))
    ):
        errors.append(f"{label} policy required status checks are not canonical unique names")
    if (
        policy.get("trusted_issuer") != "aviato-privileged-review"
        or policy.get("trusted_environment") != "privileged-review"
        or policy.get("trusted_workflow_path") != ".github/workflows/aviato-privileged-review.yml"
    ):
        errors.append(f"{label} policy trusted issuer/environment/workflow is invalid")
    signing_keys = policy.get("trusted_signing_keys")
    identities: list[tuple[str, int]] = []
    if not isinstance(signing_keys, list):
        errors.append(f"{label} policy trusted signing keys are invalid")
    else:
        for item in signing_keys:
            if not isinstance(item, dict) or set(item) != {"key_id", "key_version", "issuer", "public_key"}:
                errors.append(f"{label} policy signing-key records are not exact")
                continue
            key_id = item.get("key_id")
            version = item.get("key_version")
            public_key = item.get("public_key")
            if (
                not isinstance(key_id, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", key_id) is None
                or isinstance(version, bool)
                or not isinstance(version, int)
                or version <= 0
                or item.get("issuer") != policy.get("trusted_issuer")
                or not isinstance(public_key, str)
                or re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/]+={0,2}", public_key) is None
            ):
                errors.append(f"{label} policy signing-key identity/public key is invalid")
                continue
            identities.append((key_id, version))
        if identities != sorted(set(identities)):
            errors.append(f"{label} policy signing-key identities are duplicate or non-canonical")
    return errors


def _load_privileged_execution_manifest() -> tuple[dict[str, Any], ...]:
    if not _PRIVILEGED_MANIFEST_PATH.is_file():
        return ()
    loaded = json.loads(_PRIVILEGED_MANIFEST_PATH.read_text(encoding="utf-8"))
    return tuple(item for item in loaded if isinstance(item, dict)) if isinstance(loaded, list) else ()


# Generated from the exact reviewed workflow graph. Validation reads this package-owned contract;
# it never derives expected contracts from the consumer documents being checked.
PRIVILEGED_EXECUTION_MANIFEST = _load_privileged_execution_manifest()


def privileged_manifest_sha256(manifest: tuple[dict[str, Any], ...]) -> str:
    """Return the stable candidate identity stored in protected review records."""

    return hashlib.sha256(_json(list(manifest)).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json_mapping(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def verify_privileged_review_declaration(
    root: Path,
    *,
    manifest: tuple[dict[str, Any], ...] = PRIVILEGED_EXECUTION_MANIFEST,
) -> list[str]:
    """Validate the protected policy and an honest pending-or-approved review declaration."""

    policy_path = root / _PRIVILEGED_REVIEW_POLICY_REL
    record_path = root / _PRIVILEGED_REVIEW_RECORD_REL
    codeowners_path = root / _PRIVILEGED_CODEOWNERS_REL
    ruleset_path = root / _PRIVILEGED_RULESET_REL
    errors: list[str] = []
    policy = _load_json_mapping(policy_path)
    record = _load_json_mapping(record_path)
    codeowners = codeowners_path.read_text(encoding="utf-8") if codeowners_path.is_file() else ""
    ruleset = _load_json_mapping(ruleset_path)
    if policy is None:
        errors.append(
            "protected review declaration is missing or invalid: aviato/library/privileged-review-policy.json"
        )
    if record is None:
        errors.append("protected review declaration is missing or invalid: .github/aviato-privileged-review.json")
    if not codeowners:
        errors.append("protected review declaration is missing or invalid: .github/CODEOWNERS")
    if ruleset is None:
        errors.append("protected review declaration is missing or invalid: protect-default-branch ruleset")
    if policy is None or record is None or not codeowners or ruleset is None:
        return errors

    errors.extend(_privileged_policy_errors(policy, label="protected review"))

    if policy.get("schema_version") != 2:
        errors.append("protected review policy must use schema_version 2")
    if not isinstance(policy.get("minimum_approvals"), int) or policy["minimum_approvals"] < 2:
        errors.append("protected review policy must require at least two approvals")
    for key in (
        "require_non_author",
        "require_code_owner_review",
        "require_last_push_approval",
        "dismiss_stale_reviews_on_push",
    ):
        if policy.get(key) is not True:
            errors.append(f"protected review policy must set {key}=true")
    for key in ("reviewer_database_ids", "team_database_ids"):
        identities = policy.get(key)
        if not isinstance(identities, list) or any(
            isinstance(identity, bool) or not isinstance(identity, int) or identity <= 0 for identity in identities
        ):
            errors.append(f"protected review policy {key} must contain only positive GitHub database IDs")
        elif len(identities) != len(set(identities)):
            errors.append(f"protected review policy {key} must not contain duplicate database IDs")
    protected_paths = policy.get("protected_paths")
    if not isinstance(protected_paths, list) or any(
        path not in protected_paths for path in _PRIVILEGED_PROTECTED_PATHS
    ):
        errors.append("protected review policy does not enumerate every privileged authority path")
    for path in _PRIVILEGED_PROTECTED_PATHS:
        if f"{path} @amattas" not in codeowners:
            errors.append(f"protected review CODEOWNERS route is missing: {path}")
    if (
        policy.get("trusted_issuer") != "aviato-privileged-review"
        or policy.get("trusted_workflow_path") != ".github/workflows/aviato-privileged-review.yml"
        or policy.get("trusted_environment") != "privileged-review"
        or not isinstance(policy.get("maximum_attestation_ttl_seconds"), int)
        or not 31_536_000 <= policy["maximum_attestation_ttl_seconds"] <= 63_072_000
    ):
        errors.append("protected review policy has an invalid trusted issuer/workflow/TTL")
    if not isinstance(policy.get("trusted_signing_keys"), list) or not isinstance(
        policy.get("revoked_key_versions"), list
    ):
        errors.append("protected review policy signing-key lifecycle is invalid")
    required_checks = policy.get("required_status_checks")
    if (
        not isinstance(required_checks, list)
        or len(required_checks) < 2
        or any(not isinstance(check, str) or not check for check in required_checks)
    ):
        errors.append("protected review policy must declare its required status checks")

    pull_request: dict[str, Any] | None = None
    for rule in ruleset.get("rules") or ():
        if isinstance(rule, dict) and rule.get("type") == "pull_request" and isinstance(rule.get("parameters"), dict):
            pull_request = rule["parameters"]
            break
    if pull_request is None:
        errors.append("protected review ruleset lacks a pull_request rule")
    else:
        if pull_request.get("required_approving_review_count", 0) < 2:
            errors.append("protected review ruleset must require at least two approvals")
        for key in ("dismiss_stale_reviews_on_push", "require_code_owner_review", "require_last_push_approval"):
            if pull_request.get(key) is not True:
                errors.append(f"protected review ruleset must set {key}=true")
    if ruleset.get("enforcement") != "active" or ruleset.get("bypass_actors") != []:
        errors.append("protected review ruleset must be active without bypass actors")
    if ruleset.get("conditions") != {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}:
        errors.append("protected review ruleset must target only the default branch")
    _pull, status_checks = _ruleset_review_parameters(ruleset)
    actual_status_checks = {
        item.get("context") for item in status_checks.get("required_status_checks", []) if isinstance(item, dict)
    }
    if status_checks.get("strict_required_status_checks_policy") is not True or any(
        check not in actual_status_checks for check in (required_checks if isinstance(required_checks, list) else ())
    ):
        errors.append("protected review ruleset does not enforce the required strict status checks")

    expected_hashes = {
        "candidate_manifest_sha256": privileged_manifest_sha256(manifest),
        "policy_sha256": _file_sha256(policy_path),
        "codeowners_sha256": _file_sha256(codeowners_path),
    }
    if record.get("schema_version") != 2:
        errors.append("protected review record has an unsupported schema_version")
    if set(record) != _PRIVILEGED_REVIEW_RECORD_KEYS:
        errors.append("protected review record keys are not exact")
    if record.get("status") != "pending" or record.get("lifecycle") != "pending":
        errors.append("source protected review record must remain an honest pending prerequisite")
    request_id = record.get("activation_request_id")
    activation_nonce = record.get("activation_nonce")
    if (
        not isinstance(request_id, str)
        or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", request_id) is None
        or not _hex_digest(activation_nonce, 64)
    ):
        errors.append("protected review record activation request/nonce is invalid")
    for key, expected in expected_hashes.items():
        if record.get(key) != expected:
            errors.append(f"protected review record {key} does not bind the current protected candidate")
    if not isinstance(record.get("approvals"), list):
        errors.append("protected review record approvals must be a list")
    return errors


def verify_privileged_review_readiness(
    root: Path,
    *,
    manifest: tuple[dict[str, Any], ...] = PRIVILEGED_EXECUTION_MANIFEST,
) -> list[str]:
    """Require concrete, protected, non-author approval evidence before privileged activation."""

    errors = verify_privileged_review_declaration(root, manifest=manifest)
    if errors:
        return errors
    policy = _load_json_mapping(root / _PRIVILEGED_REVIEW_POLICY_REL) or {}
    record = _load_json_mapping(root / _PRIVILEGED_REVIEW_RECORD_REL) or {}
    # Source-tree declarations never self-authorize. The only operationally
    # approved form is the separately signed packaged envelope verified live.
    if record.get("status") != "approved":
        return ["protected review is pending: configure reviewer/team IDs and record protected approvals"]
    reviewer_ids = policy.get("reviewer_database_ids") or []
    team_ids = policy.get("team_database_ids") or []
    if not reviewer_ids and not team_ids:
        errors.append("protected review has no configured reviewer or team database IDs")
    author_id = record.get("author_database_id")
    if isinstance(author_id, bool) or not isinstance(author_id, int) or author_id <= 0:
        errors.append("protected review record requires a positive author_database_id")
    minimum = int(policy["minimum_approvals"])
    approvals = record.get("approvals") or []
    approved_reviewers: set[int] = set()
    for approval in approvals:
        if not isinstance(approval, dict):
            errors.append("protected review approval entries must be mappings")
            continue
        reviewer_id = approval.get("reviewer_database_id")
        review_id = approval.get("review_id")
        if isinstance(reviewer_id, bool) or not isinstance(reviewer_id, int) or reviewer_id <= 0:
            errors.append("protected review approval requires a positive reviewer_database_id")
            continue
        if isinstance(review_id, bool) or not isinstance(review_id, int) or review_id <= 0:
            errors.append("protected review approval requires a positive immutable review_id")
        if reviewer_id == author_id:
            errors.append("protected review approval must be from a non-author")
        team_id = approval.get("team_database_id")
        if reviewer_id not in reviewer_ids and team_id not in team_ids:
            errors.append("protected review approval is not bound to a configured reviewer or team database ID")
        approved_reviewers.add(reviewer_id)
    if len(approved_reviewers) < minimum:
        errors.append(f"protected review requires {minimum} distinct recorded approving reviewers")
    return errors


def _positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _hex_digest(value: object, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None


def _canonical_base64url(value: object) -> bytes | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        return None
    if not decoded or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        return None
    return decoded


def _ruleset_review_parameters(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    pull_request: dict[str, Any] = {}
    status_checks: dict[str, Any] = {}
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return pull_request, status_checks
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("parameters"), dict):
            continue
        if rule.get("type") == "pull_request":
            pull_request = rule["parameters"]
        elif rule.get("type") == "required_status_checks":
            status_checks = rule["parameters"]
    return pull_request, status_checks


def _protected_path_covered(path: str, protected: list[str]) -> bool:
    return any(path == candidate or (candidate.endswith("/") and path.startswith(candidate)) for candidate in protected)


def verify_privileged_review_envelope(
    envelope: dict[str, Any],
    *,
    trusted_base_policy: dict[str, Any],
    current_policy: dict[str, Any],
    live_evidence: dict[str, Any] | None,
    now: int,
    verify_signature: Callable[[bytes, bytes, bytes, str], bool],
) -> list[str]:
    """Verify one canonical signed review envelope against fresh external state.

    ``trusted_base_policy`` is deliberately separate from candidate/package
    policy. The operational collector obtains it from the evidence PR's base
    SHA (or an installed predecessor trust root); a candidate cannot replace a
    key and then use that replacement to self-approve.
    """

    errors: list[str] = []
    policy_errors = [
        *_privileged_policy_errors(trusted_base_policy, label="trusted base"),
        *_privileged_policy_errors(current_policy, label="current default-branch"),
    ]
    if policy_errors:
        return policy_errors
    if not isinstance(current_policy, dict):
        current_policy = {}
        errors.append("protected review current default-branch policy is unavailable")
    if (
        current_policy.get("trusted_issuer") != trusted_base_policy.get("trusted_issuer")
        or current_policy.get("trusted_workflow_path") != trusted_base_policy.get("trusted_workflow_path")
        or current_policy.get("trusted_environment") != trusted_base_policy.get("trusted_environment")
    ):
        errors.append("protected review current policy changed the immutable issuer/workflow trust identity")
    if current_policy.get("protected_paths") != trusted_base_policy.get("protected_paths"):
        errors.append("protected review current policy changed the protected-path trust boundary")
    for flag in (
        "require_non_author",
        "require_code_owner_review",
        "require_last_push_approval",
        "dismiss_stale_reviews_on_push",
    ):
        if trusted_base_policy.get(flag) is not True or current_policy.get(flag) is not True:
            errors.append(f"protected review base/current policy intersection does not require {flag}")
    if not isinstance(envelope, dict) or set(envelope) != {"schema", "algorithm", "evidence", "signature"}:
        return ["protected review requires one exact canonical envelope with a signature"]
    if envelope.get("schema") != "aviato-privileged-review-envelope/v1":
        errors.append("protected review envelope schema is unsupported")
    if envelope.get("algorithm") != "ssh-ed25519":
        errors.append("protected review envelope signature algorithm is unsupported")
    evidence = envelope.get("evidence")
    if not isinstance(evidence, dict):
        return [*errors, "protected review envelope evidence is missing"]
    signature = _canonical_base64url(envelope.get("signature"))
    if signature is None:
        errors.append("protected review envelope signature is missing or non-canonical")

    required_evidence = {
        "schema",
        "status",
        "lifecycle",
        "repository",
        "pull_request",
        "activation_request",
        "protected_files",
        "changed_protected_paths",
        "reviews",
        "ruleset",
        "collector",
        "environment",
        "issuer",
        "workflow",
        "trust_root",
        "issued_at",
        "expires_at",
        "key_id",
        "key_version",
        "nonce",
    }
    if set(evidence) != required_evidence:
        errors.append("protected review evidence keys are not exact")
    if (
        evidence.get("schema") != "aviato-privileged-review-evidence/v1"
        or evidence.get("status") != "approved"
        or evidence.get("lifecycle") != "consumed"
    ):
        errors.append("protected review evidence did not complete pending, approved, consumed lifecycle")

    repository = evidence.get("repository")
    pull_request = evidence.get("pull_request")
    workflow = evidence.get("workflow")
    trust_root = evidence.get("trust_root")
    if not isinstance(repository, dict) or set(repository) != {
        "database_id",
        "node_id",
        "full_name",
        "default_branch",
    }:
        errors.append("protected review repository identity is incomplete")
        repository = {}
    if (
        not _positive_int(repository.get("database_id"))
        or not isinstance(repository.get("node_id"), str)
        or not repository.get("node_id")
        or not isinstance(repository.get("full_name"), str)
        or "/" not in str(repository.get("full_name"))
        or not isinstance(repository.get("default_branch"), str)
        or not repository.get("default_branch")
    ):
        errors.append("protected review repository identity is invalid")
    if not isinstance(pull_request, dict) or set(pull_request) != {
        "number",
        "author_database_id",
        "author_login",
        "base_sha",
        "head_sha",
        "last_push_sha",
        "last_push_at",
        "merged_sha",
        "merged_at",
        "merger_database_id",
        "merger_login",
        "protected_tree_root",
    }:
        errors.append("protected review pull request identity is incomplete")
        pull_request = {}
    if not _positive_int(pull_request.get("number")) or not _positive_int(pull_request.get("author_database_id")):
        errors.append("protected review pull request/author identity is invalid")
    for name in ("base_sha", "head_sha", "last_push_sha", "merged_sha"):
        if not _hex_digest(pull_request.get(name), 40):
            errors.append(f"protected review pull request {name} is invalid")
    if pull_request.get("head_sha") != pull_request.get("last_push_sha"):
        errors.append("protected review head does not equal the latest pushed commit")
    last_push_at = _parse_timestamp(pull_request.get("last_push_at"))
    if last_push_at is None:
        errors.append("protected review last-push time is invalid")
    merged_at = _parse_timestamp(pull_request.get("merged_at"))
    if (
        merged_at is None
        or not _positive_int(pull_request.get("merger_database_id"))
        or not isinstance(pull_request.get("merger_login"), str)
        or not pull_request.get("merger_login")
    ):
        errors.append("protected review merge time/identity is invalid")

    activation_request = evidence.get("activation_request")
    if not isinstance(activation_request, dict) or set(activation_request) != {
        "request_id",
        "nonce",
        "anchor_sha256",
    }:
        errors.append("protected review activation request is incomplete")
        activation_request = {}
    if (
        not isinstance(activation_request.get("request_id"), str)
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            str(activation_request.get("request_id")),
        )
        is None
        or not _hex_digest(activation_request.get("nonce"), 64)
        or not _hex_digest(activation_request.get("anchor_sha256"), 64)
    ):
        errors.append("protected review activation request identity/nonce is invalid")

    protected_files = evidence.get("protected_files")
    protected_policy_paths = trusted_base_policy.get("protected_paths")
    if not isinstance(protected_files, list) or not protected_files:
        errors.append("protected review protected-file inventory is empty")
        protected_files = []
    if not isinstance(protected_policy_paths, list) or any(
        not isinstance(path, str) for path in protected_policy_paths
    ):
        errors.append("trusted base policy protected paths are invalid")
        protected_policy_paths = []
    seen_paths: set[str] = set()
    for item in protected_files:
        if not isinstance(item, dict) or set(item) != {"path", "mode", "sha256"}:
            errors.append("protected review file entries must bind exact path, mode, and SHA-256")
            continue
        path = item.get("path")
        mode = item.get("mode")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path in seen_paths
            or not isinstance(mode, str)
            or re.fullmatch(r"100(?:644|755)", mode) is None
            or not _hex_digest(item.get("sha256"), 64)
        ):
            errors.append("protected review file identity is invalid, duplicate, or non-regular")
            continue
        seen_paths.add(path)
        if not _protected_path_covered(path, protected_policy_paths):
            errors.append(f"protected review file is outside trusted base policy: {path}")
    if [item.get("path") for item in protected_files if isinstance(item, dict)] != sorted(seen_paths):
        errors.append("protected review file inventory is not unique canonical path order")
    for protected_path in protected_policy_paths:
        if not any(
            path == protected_path or (protected_path.endswith("/") and path.startswith(protected_path))
            for path in seen_paths
        ):
            errors.append(f"protected review omitted trusted protected path: {protected_path}")
    if pull_request.get("protected_tree_root") != _digest(protected_files):
        errors.append("protected review protected-tree root is invalid")
    changed_paths = evidence.get("changed_protected_paths")
    if not isinstance(changed_paths, list) or changed_paths != sorted(set(changed_paths)):
        errors.append("protected review changed protected paths are ambiguous or non-canonical")
        changed_paths = []
    if any(path not in seen_paths for path in changed_paths):
        errors.append("protected review changed path lacks a content/mode identity")
    activation_anchor = "/.github/aviato-privileged-review.json"
    anchor_files = [
        item for item in protected_files if isinstance(item, dict) and item.get("path") == activation_anchor
    ]
    if (
        activation_anchor not in changed_paths
        or len(anchor_files) != 1
        or activation_request.get("anchor_sha256") != anchor_files[0].get("sha256")
    ):
        errors.append("protected review activation anchor is absent, unchanged, or not content-bound")

    required_workflow = {
        "repository_id",
        "path",
        "ref",
        "blob_sha",
        "blob_sha256",
        "run_head_sha",
        "run_id",
        "workflow_database_id",
        "run_attempt",
        "event",
        "status",
        "conclusion",
        "actor_database_id",
        "actor_login",
        "triggering_actor_database_id",
        "triggering_actor_login",
        "environment",
    }
    if not isinstance(workflow, dict) or set(workflow) != required_workflow:
        errors.append("protected review trusted workflow identity is incomplete")
        workflow = {}
    expected_ref = f"refs/heads/{repository.get('default_branch')}"
    if (
        workflow.get("repository_id") != repository.get("database_id")
        or workflow.get("path") != trusted_base_policy.get("trusted_workflow_path")
        or workflow.get("ref") != expected_ref
        or not _hex_digest(workflow.get("blob_sha"), 40)
        or not _hex_digest(workflow.get("blob_sha256"), 64)
        or workflow.get("run_head_sha") != pull_request.get("merged_sha")
        or not _positive_int(workflow.get("run_id"))
        or not _positive_int(workflow.get("workflow_database_id"))
        or not _positive_int(workflow.get("run_attempt"))
        or workflow.get("event") != "workflow_dispatch"
        or workflow.get("status") != "completed"
        or workflow.get("conclusion") != "success"
        or not _positive_int(workflow.get("actor_database_id"))
        or not isinstance(workflow.get("actor_login"), str)
        or not workflow.get("actor_login")
        or not _positive_int(workflow.get("triggering_actor_database_id"))
        or not isinstance(workflow.get("triggering_actor_login"), str)
        or not workflow.get("triggering_actor_login")
        or workflow.get("environment") != trusted_base_policy.get("trusted_environment")
    ):
        errors.append("protected review was not issued by the trusted default-branch workflow")
    required_trust_root = {
        "base_sha",
        "policy_blob_sha",
        "policy_sha256",
        "codeowners_blob_sha",
        "codeowners_sha256",
    }
    if not isinstance(trust_root, dict) or set(trust_root) != required_trust_root:
        errors.append("protected review trusted-base policy root is incomplete")
        trust_root = {}
    if (
        trust_root.get("base_sha") != pull_request.get("base_sha")
        or not _hex_digest(trust_root.get("policy_blob_sha"), 40)
        or trust_root.get("policy_sha256") != _digest(trusted_base_policy)
        or not _hex_digest(trust_root.get("codeowners_blob_sha"), 40)
        or not _hex_digest(trust_root.get("codeowners_sha256"), 64)
    ):
        errors.append("protected review does not bind the immutable trusted base policy")

    issued_at = evidence.get("issued_at")
    expires_at = evidence.get("expires_at")
    base_ttl = trusted_base_policy.get("maximum_attestation_ttl_seconds")
    current_ttl = current_policy.get("maximum_attestation_ttl_seconds")
    base_ttl_seconds = base_ttl if _positive_int(base_ttl) else 0
    current_ttl_seconds = current_ttl if _positive_int(current_ttl) else 0
    assert isinstance(base_ttl_seconds, int) and isinstance(current_ttl_seconds, int)
    maximum_ttl = min(base_ttl_seconds, current_ttl_seconds)
    issued_epoch = issued_at if _positive_int(issued_at) else 0
    expiry_epoch = expires_at if _positive_int(expires_at) else 0
    maximum_ttl_seconds = maximum_ttl if _positive_int(maximum_ttl) else 0
    assert isinstance(issued_epoch, int) and isinstance(expiry_epoch, int) and isinstance(maximum_ttl_seconds, int)
    if (
        not issued_epoch
        or not expiry_epoch
        or not maximum_ttl_seconds
        or expiry_epoch <= issued_epoch
        or expiry_epoch - issued_epoch > maximum_ttl_seconds
        or now < issued_epoch - 30
        or now >= expiry_epoch
    ):
        errors.append("protected review signed evidence is not currently fresh")
    if evidence.get("issuer") != trusted_base_policy.get("trusted_issuer"):
        errors.append("protected review issuer is not trusted")
    if not _hex_digest(evidence.get("nonce"), 64):
        errors.append("protected review replay nonce is invalid")

    key_id = evidence.get("key_id")
    key_version = evidence.get("key_version")
    signing_keys = trusted_base_policy.get("trusted_signing_keys")
    current_signing_keys = current_policy.get("trusted_signing_keys")
    revoked = trusted_base_policy.get("revoked_key_versions")
    current_revoked = current_policy.get("revoked_key_versions")
    selected: list[dict[str, Any]] = []
    current_selected: list[dict[str, Any]] = []
    if isinstance(signing_keys, list):
        selected = [
            item
            for item in signing_keys
            if isinstance(item, dict)
            and item.get("key_id") == key_id
            and item.get("key_version") == key_version
            and item.get("issuer") == evidence.get("issuer")
        ]
    if isinstance(current_signing_keys, list):
        current_selected = [
            item
            for item in current_signing_keys
            if isinstance(item, dict)
            and item.get("key_id") == key_id
            and item.get("key_version") == key_version
            and item.get("issuer") == evidence.get("issuer")
        ]
    if not isinstance(revoked, list):
        revoked = []
    if not isinstance(current_revoked, list):
        current_revoked = []
    if key_version in revoked or key_version in current_revoked:
        errors.append("protected review signing key version is revoked")
    if (
        len(selected) != 1
        or len(current_selected) != 1
        or not isinstance(selected[0].get("public_key"), str)
        or current_selected[0].get("public_key") != selected[0].get("public_key")
    ):
        errors.append("protected review signing key is absent or changed in base/current policy intersection")
    elif signature is not None:
        try:
            verified = verify_signature(
                selected[0]["public_key"].encode("ascii"),
                _json(evidence).encode("ascii"),
                signature,
                str(evidence.get("issuer")),
            )
        except Exception:  # fail closed across binary/key/API verifier failures
            verified = False
        if verified is not True:
            errors.append("protected review signature verification failed")

    reviews = evidence.get("reviews")
    base_minimum = trusted_base_policy.get("minimum_approvals")
    current_minimum = current_policy.get("minimum_approvals")
    base_minimum_count = base_minimum if _positive_int(base_minimum) else 0
    current_minimum_count = current_minimum if _positive_int(current_minimum) else 0
    assert isinstance(base_minimum_count, int) and isinstance(current_minimum_count, int)
    minimum = max(base_minimum_count, current_minimum_count)
    base_reviewers = trusted_base_policy.get("reviewer_database_ids")
    current_reviewers = current_policy.get("reviewer_database_ids")
    base_teams = trusted_base_policy.get("team_database_ids")
    current_teams = current_policy.get("team_database_ids")
    allowed_reviewers = (
        sorted(set(base_reviewers) & set(current_reviewers))
        if isinstance(base_reviewers, list) and isinstance(current_reviewers, list)
        else []
    )
    allowed_teams = (
        sorted(set(base_teams) & set(current_teams))
        if isinstance(base_teams, list) and isinstance(current_teams, list)
        else []
    )
    if not isinstance(reviews, list) or not _positive_int(minimum):
        errors.append("protected review approval evidence or minimum is invalid")
        reviews = []
        minimum = 2
    if not isinstance(allowed_reviewers, list):
        allowed_reviewers = []
    if not isinstance(allowed_teams, list):
        allowed_teams = []
    reviewer_ids: set[int] = set()
    review_ids: set[int] = set()
    for review in reviews:
        if not isinstance(review, dict):
            errors.append("protected review approval entries must be mappings")
            continue
        required_review = {
            "review_id",
            "node_id",
            "reviewer_database_id",
            "reviewer_login",
            "state",
            "commit_sha",
            "submitted_at",
            "dismissed",
            "edited",
            "is_author",
            "eligible_codeowner_paths",
            "team_database_id",
            "team_membership",
        }
        if set(review) != required_review:
            errors.append("protected review approval identity is incomplete")
            continue
        reviewer_id = review.get("reviewer_database_id")
        review_id = review.get("review_id")
        team_id = review.get("team_database_id")
        submitted = _parse_timestamp(review.get("submitted_at"))
        reviewer_database_id = reviewer_id if _positive_int(reviewer_id) else None
        immutable_review_id = review_id if _positive_int(review_id) else None
        assert reviewer_database_id is None or isinstance(reviewer_database_id, int)
        assert immutable_review_id is None or isinstance(immutable_review_id, int)
        if reviewer_database_id is None or reviewer_database_id in reviewer_ids:
            errors.append("protected review requires distinct concrete reviewer database IDs")
        else:
            reviewer_ids.add(reviewer_database_id)
        if (
            immutable_review_id is None
            or immutable_review_id in review_ids
            or not str(review.get("node_id", "")).startswith("PRR_")
        ):
            errors.append("protected review requires unique immutable review IDs/node IDs")
        else:
            review_ids.add(immutable_review_id)
        if reviewer_id == pull_request.get("author_database_id") or review.get("is_author") is not False:
            errors.append("protected review approval must be from a live-proven non-author")
        eligible = reviewer_database_id in allowed_reviewers
        if team_id is not None:
            eligible = eligible or (team_id in allowed_teams and review.get("team_membership") is True)
        if not eligible:
            errors.append("protected review approval is not a current eligible reviewer/team member")
        if (
            review.get("state") != "APPROVED"
            or review.get("dismissed") is not False
            or review.get("edited") is not False
            or review.get("commit_sha") != pull_request.get("last_push_sha")
            or submitted is None
            or last_push_at is None
            or submitted <= last_push_at
            or merged_at is None
            or submitted > merged_at
        ):
            errors.append("protected review approval is stale, dismissed, edited, or for the wrong commit")
        owned = review.get("eligible_codeowner_paths")
        if not isinstance(owned, list) or any(path not in owned for path in changed_paths):
            errors.append("protected review approval is not an eligible CODEOWNER for every changed protected path")
    minimum_count = minimum if _positive_int(minimum) else 2
    assert isinstance(minimum_count, int)
    if len(reviewer_ids) < minimum_count:
        errors.append(f"protected review requires {minimum_count} distinct current approving reviewers")

    environment = evidence.get("environment")
    if not isinstance(environment, dict) or set(environment) != {
        "name",
        "can_admins_bypass",
        "prevent_self_review",
        "reviewers",
        "deployment_branch_policy",
        "payload_sha256",
    }:
        errors.append("protected review environment authority is incomplete")
        environment = {}
    environment_body = {key: value for key, value in environment.items() if key != "payload_sha256"}
    environment_reviewers = environment.get("reviewers")
    eligible_environment_reviewers: set[tuple[str, int]] = set()
    if isinstance(environment_reviewers, list):
        for reviewer in environment_reviewers:
            if not isinstance(reviewer, dict) or set(reviewer) != {"type", "database_id", "node_id", "login"}:
                continue
            database_id = reviewer.get("database_id")
            concrete_database_id = database_id if _positive_int(database_id) else None
            assert concrete_database_id is None or isinstance(concrete_database_id, int)
            kind = reviewer.get("type")
            if (
                concrete_database_id is not None
                and kind in {"User", "Team"}
                and isinstance(reviewer.get("node_id"), str)
                and reviewer.get("node_id")
                and isinstance(reviewer.get("login"), str)
                and reviewer.get("login")
                and (
                    (kind == "User" and concrete_database_id in allowed_reviewers)
                    or (kind == "Team" and concrete_database_id in allowed_teams)
                )
            ):
                eligible_environment_reviewers.add((kind, concrete_database_id))
    if (
        environment.get("name") != trusted_base_policy.get("trusted_environment")
        or environment.get("can_admins_bypass") is not False
        or environment.get("prevent_self_review") is not True
        or environment.get("deployment_branch_policy") != {"protected_branches": True, "custom_branch_policies": False}
        or environment.get("payload_sha256") != _digest(environment_body)
        or len(eligible_environment_reviewers) < minimum_count
    ):
        errors.append("protected review environment lacks independent protected reviewers or permits bypass")

    collector = evidence.get("collector")
    required_app_permissions = {
        "actions": "read",
        "administration": "read",
        "contents": "read",
        "members": "read",
        "metadata": "read",
        "pull_requests": "read",
    }
    if not isinstance(collector, dict) or set(collector) != {
        "app_id",
        "installation_id",
        "app_slug",
        "permissions",
        "repository_ids",
        "suspended_at",
    }:
        errors.append("protected review collector is not one exact GitHub App installation")
    elif (
        not _positive_int(collector.get("app_id"))
        or not _positive_int(collector.get("installation_id"))
        or not isinstance(collector.get("app_slug"), str)
        or not collector.get("app_slug")
        or collector.get("permissions") != required_app_permissions
        or collector.get("suspended_at") is not None
        or not isinstance(collector.get("repository_ids"), list)
        or collector["repository_ids"].count(repository.get("database_id")) != 1
    ):
        errors.append("protected review collector App is suspended, over-scoped, or does not select this repository")

    ruleset = evidence.get("ruleset")
    if not isinstance(ruleset, dict) or set(ruleset) != {"payload", "payload_sha256"}:
        errors.append("protected review live ruleset identity is incomplete")
        ruleset = {}
    payload = ruleset.get("payload")
    if not isinstance(payload, dict) or ruleset.get("payload_sha256") != _digest(payload):
        errors.append("protected review live ruleset canonical payload/hash is invalid")
        payload = {}
    if (
        not _positive_int(payload.get("id"))
        or not isinstance(payload.get("node_id"), str)
        or not payload.get("node_id")
        or payload.get("source") != repository.get("full_name")
        or payload.get("source_type") != "Repository"
        or payload.get("target") != "branch"
        or payload.get("enforcement") != "active"
        or payload.get("bypass_actors") != []
        or payload.get("current_user_can_bypass") is not False
        or payload.get("conditions") != {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    ):
        errors.append("protected review ruleset is disabled, bypassed, or targets the wrong repository/branch")
    pull_parameters, check_parameters = _ruleset_review_parameters(payload)
    if (
        pull_parameters.get("required_approving_review_count", 0) < minimum
        or pull_parameters.get("dismiss_stale_reviews_on_push") is not True
        or pull_parameters.get("require_code_owner_review") is not True
        or pull_parameters.get("require_last_push_approval") is not True
    ):
        errors.append("protected review ruleset does not enforce the complete review policy")
    base_checks = trusted_base_policy.get("required_status_checks")
    current_checks = current_policy.get("required_status_checks")
    required_checks = (
        sorted(set(base_checks) | set(current_checks))
        if isinstance(base_checks, list)
        and isinstance(current_checks, list)
        and all(isinstance(item, str) and item for item in [*base_checks, *current_checks])
        else None
    )
    actual_checks = {
        item.get("context")
        for item in check_parameters.get("required_status_checks", [])
        if isinstance(item, dict) and isinstance(item.get("context"), str)
    }
    if (
        check_parameters.get("strict_required_status_checks_policy") is not True
        or not isinstance(required_checks, list)
        or any(check not in actual_checks for check in required_checks)
    ):
        errors.append("protected review ruleset lacks required strict status checks")

    if live_evidence is None:
        errors.append("protected review live API evidence is unavailable")
    elif _json(live_evidence) != _json(evidence):
        errors.append("protected review signed evidence does not exactly match one current unambiguous live snapshot")
    return errors


def verify_packaged_privileged_review_readiness(
    data_root: Path,
    *,
    collect_live: Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] | None = None,
    verify_signature: Callable[[bytes, bytes, bytes, str], bool] | None = None,
    now: int | None = None,
) -> list[str]:
    """Verify the protected review evidence shipped with an installed Library snapshot."""

    policy_path = data_root / "privileged-review-policy.json"
    manifest_path = data_root / "privileged-execution-manifest.json"
    record_path = data_root / _PRIVILEGED_REVIEW_ATTESTATION_NAME
    policy = _load_json_mapping(policy_path)
    record = _load_json_mapping(record_path)
    try:
        loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        loaded_manifest = None
    if policy is None or record is None or not isinstance(loaded_manifest, list):
        return ["protected review package attestation is missing or invalid"]
    manifest = tuple(item for item in loaded_manifest if isinstance(item, dict))
    if len(manifest) != len(loaded_manifest):
        return ["protected review package manifest must contain only job contracts"]
    if record.get("status") == "pending":
        return ["protected review is pending: configure real identities, active ruleset, and signed live approvals"]
    if record.get("schema") != "aviato-privileged-review-envelope/v1":
        return ["protected review package requires a canonical signed live evidence envelope"]
    if collect_live is None or verify_signature is None or now is None:
        try:
            from .privileged_review import collect_live_privileged_review_evidence, verify_ssh_review_signature

            collect_live = collect_live or collect_live_privileged_review_evidence
            verify_signature = verify_signature or verify_ssh_review_signature
            if now is None:
                import time

                now = int(time.time())
        except (ImportError, OSError, ValueError) as exc:
            return [f"protected review live verifier is unavailable: {exc}"]
    try:
        trusted_base_policy, current_policy, live_evidence = collect_live(record)
    except Exception as exc:
        return [f"protected review live API evidence is unavailable or ambiguous: {exc}"]
    errors = verify_privileged_review_envelope(
        record,
        trusted_base_policy=trusted_base_policy,
        current_policy=current_policy,
        live_evidence=live_evidence,
        now=now,
        verify_signature=verify_signature,
    )
    evidence = record.get("evidence") if isinstance(record, dict) else None
    if isinstance(evidence, dict):
        protected = evidence.get("protected_files")
        if isinstance(protected, list):
            hashes = {
                item.get("path"): item.get("sha256")
                for item in protected
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
            local_bindings = {
                "/aviato/library/privileged-execution-manifest.json": manifest_path,
                "/aviato/library/privileged-review-policy.json": policy_path,
                "/aviato/plugins/release_mutations.py": Path(__file__),
                "/aviato/plugins/privileged_review.py": Path(__file__).with_name("privileged_review.py"),
                "/aviato/cli.py": Path(__file__).parents[1] / "cli.py",
            }
            for logical, path in local_bindings.items():
                if hashes.get(logical) != _file_sha256(path):
                    errors.append(f"protected review package does not match reviewed protected file: {logical}")
    return errors


_DANGEROUS_EXACT_CONTEXT = {
    "BASH_ENV",
    "BASHOPTS",
    "CURL_CA_BUNDLE",
    "ENV",
    "NODE_OPTIONS",
    "NO_PROXY",
    "PATH",
    "PERL5OPT",
    "REQUESTS_CA_BUNDLE",
    "RUBYOPT",
    "SHELLOPTS",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
}


def _dangerous_context_key(key: object) -> bool:
    name = str(key).upper()
    return (
        name in _DANGEROUS_EXACT_CONTEXT
        or name.startswith(("DYLD_", "GITHUB_", "LD_", "PYTHON", "SSL_CERT_"))
        or name.endswith("_PROXY")
    )


def _pairs(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(sorted((str(key), str(item)) for key, item in value.items()))


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _workflow_document_digest(document: dict[str, Any]) -> str:
    """Canonicalize PyYAML's YAML-1.1 boolean `on` key before hashing."""

    def normalize(value: object) -> object:
        if isinstance(value, dict):
            normalized: dict[str, object] = {}
            for key, item in value.items():
                name = "on" if key is True else "off" if key is False else str(key)
                if name in normalized:
                    raise ValueError(f"workflow has colliding canonical key: {name}")
                normalized[name] = normalize(item)
            return normalized
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    return _digest(normalize(document))


def _privileged_job_contract(
    workflow: str,
    job_name: str,
    document: dict[str, Any],
    job: dict[str, Any],
    permissions: dict[str, Any],
    trust_edge: str,
) -> PrivilegedJobContract:
    steps = tuple(step for step in job.get("steps") or () if isinstance(step, dict))
    return PrivilegedJobContract(
        workflow=workflow,
        job=job_name,
        trust_edge=trust_edge,
        # Bind the complete canonical workflow, not only the selected job. This
        # covers every trigger (including pull_request_target), the complete
        # workflow_call interface, concurrency, name/run-name, defaults/env,
        # permissions, and sibling authority producers in one exact identity.
        workflow_sha256=_workflow_document_digest(document),
        permissions=_pairs(permissions),
        workflow_env_keys=tuple(sorted(str(key) for key in (document.get("env") or {}))),
        workflow_env_sha256=_digest(document.get("env")),
        workflow_defaults_sha256=_digest(document.get("defaults")),
        needs_sha256=_digest(job.get("needs")),
        outputs_sha256=_digest(job.get("outputs")),
        job_env_keys=tuple(sorted(str(key) for key in (job.get("env") or {}))),
        job_env_sha256=_digest(job.get("env")),
        job_defaults_sha256=_digest(job.get("defaults")),
        container_sha256=_digest(job.get("container")),
        services_sha256=_digest(job.get("services")),
        step_order=tuple((str(step.get("id", "")), str(step.get("name", ""))) for step in steps),
        step_uses=tuple(str(step.get("uses", "")) for step in steps),
        step_run_sha256=tuple(
            hashlib.sha256(str(step.get("run", "")).encode("utf-8")).hexdigest() if "run" in step else ""
            for step in steps
        ),
        step_shells=tuple(str(step.get("shell", "")) for step in steps),
        step_env_keys=tuple(tuple(sorted(str(key) for key in (step.get("env") or {}))) for step in steps),
        step_env_sha256=tuple(_digest(step.get("env")) for step in steps),
        job_sha256=hashlib.sha256(_json(job).encode("utf-8")).hexdigest(),
    )


def _actual_trust_edge(
    workflow: str,
    job_name: str,
    job: dict[str, Any],
    permissions: dict[str, Any],
    *,
    producer: bool = False,
) -> str:
    if workflow == "aviato-protection-checkpoint.yml" and job_name == "attest":
        return "fixed-verified-artifact"
    if permissions.get("id-token") == "write":
        return "adjacent-live-verifier"
    if "uses" in job:
        return "delegated-reusable-workflow"
    if job_name == "status-bridge":
        return "generated-status-bridge"
    if producer:
        return "transitive-authority-producer"
    if _trust_sensitive_seed(workflow, job_name, job, permissions):
        return "trust-sensitive-job"
    return "exact-privileged-job"


_NEEDS_REFERENCE = re.compile(r"\bneeds\.([A-Za-z0-9_-]+)\b")
_MUTATION_CREDENTIAL_EXACT = {
    "APP_STORE_CONNECT_API_KEY",
    "APP_STORE_CONNECT_ISSUER_ID",
    "APP_STORE_CONNECT_KEY_ID",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "NPM_TOKEN",
    "PYPI_API_TOKEN",
    "TWINE_PASSWORD",
}
_MUTATION_CREDENTIAL_MARKERS = ("APP_STORE_CONNECT", "DEPLOY", "PUBLISH", "RELEASE", "SIGNING", "TOKEN")
_ALLOWED_PERMISSION_LEVELS = {"read", "write", "none"}
_EXPRESSION = re.compile(r"\$\{\{(?P<body>.*?)\}\}", re.DOTALL)


def _job_needs(job: dict[str, Any]) -> set[str]:
    value = job.get("needs")
    if isinstance(value, str):
        needed = {value}
    elif isinstance(value, list):
        needed = {str(item) for item in value}
    else:
        needed = set()
    needed.update(_NEEDS_REFERENCE.findall(_json(job)))
    return needed


def _job_env_keys(job: dict[str, Any]) -> set[str]:
    keys = {str(key).upper() for key in (job.get("env") or {})}
    for step in job.get("steps") or ():
        if isinstance(step, dict):
            keys.update(str(key).upper() for key in (step.get("env") or {}))
    return keys


def _validated_permissions(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} permissions must be an explicit mapping")
    for scope, level in value.items():
        if not isinstance(scope, str) or not scope or level not in _ALLOWED_PERMISSION_LEVELS:
            raise ValueError(f"{label} permissions contain an unknown scope/value")
    return value


def _contains_credential_context(value: object) -> bool:
    """Structurally find credential expressions without serialized-substring shortcuts."""

    if isinstance(value, dict):
        return any(
            _contains_credential_context(key) or _contains_credential_context(item) for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_credential_context(item) for item in value)
    if not isinstance(value, str):
        return False
    for match in _EXPRESSION.finditer(value):
        body = match.group("body").casefold()
        if re.search(r"\bsecrets\s*(?:\.|\[)", body):
            return True
        if re.search(r"\bgithub\s*\.\s*token\b", body):
            return True
        # Any dynamic bracket selection from github may resolve to token and is
        # therefore conservatively enrolled.
        if re.search(r"\bgithub\s*\[", body):
            return True
    return False


def _trust_sensitive_seed(
    workflow: str,
    job_name: str,
    job: dict[str, Any],
    permissions: dict[str, Any],
) -> bool:
    """Classify every job that can exercise or authorize a repository trust edge."""

    if any(value == "write" for value in permissions.values()):
        return True
    if job.get("environment") not in (None, "", {}):
        return True
    if "secrets" in job or _contains_credential_context(job):
        return True
    env_keys = _job_env_keys(job)
    if any(
        key in _MUTATION_CREDENTIAL_EXACT or any(marker in key for marker in _MUTATION_CREDENTIAL_MARKERS)
        for key in env_keys
    ):
        return True
    if (workflow, job_name) in {(item.workflow, item.job) for item in HOSTED_MUTATIONS}:
        return True
    for step in job.get("steps") or ():
        if not isinstance(step, dict):
            continue
        uses = str(step.get("uses", "")).split("@", 1)[0]
        if uses in _ACTION_KINDS and _ACTION_KINDS[uses] == "oidc-attestation":
            return True
        if any(_mutation_markers(command) for command in _shell_commands(str(step.get("run", "")))):
            return True
    return False


def _privileged_jobs(documents: dict[str, dict[str, Any]]) -> dict[tuple[str, str], PrivilegedJobContract]:
    found: dict[tuple[str, str], PrivilegedJobContract] = {}
    for workflow, document in documents.items():
        if "permissions" not in document:
            raise ValueError(f"{workflow} workflow permissions must be an explicit mapping")
        top_permissions = _validated_permissions(document["permissions"], label=f"{workflow} workflow")
        jobs = document.get("jobs") or {}
        if not isinstance(jobs, dict):
            raise ValueError(f"{workflow} jobs must be a mapping")
        selected: set[str] = set()
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            permissions = (
                _validated_permissions(job["permissions"], label=f"{workflow}:{job_name} job")
                if "permissions" in job
                else top_permissions
            )
            if "uses" in job or _trust_sensitive_seed(workflow, str(job_name), job, permissions):
                selected.add(str(job_name))

        seeds = set(selected)
        pending = list(selected)
        while pending:
            selected_job = jobs.get(pending.pop())
            if not isinstance(selected_job, dict):
                continue
            for producer in _job_needs(selected_job):
                if producer not in selected and isinstance(jobs.get(producer), dict):
                    selected.add(producer)
                    pending.append(producer)

        for job_name in sorted(selected):
            job = jobs[job_name]
            permissions = job.get("permissions") if "permissions" in job else top_permissions
            permissions = _validated_permissions(permissions, label=f"{workflow}:{job_name} job")
            key = (workflow, str(job_name))
            found[key] = _privileged_job_contract(
                workflow,
                str(job_name),
                document,
                job,
                permissions,
                _actual_trust_edge(workflow, str(job_name), job, permissions, producer=job_name not in seeds),
            )
    return found


def verify_privileged_execution_documents(
    documents: dict[str, dict[str, Any]],
    *,
    manifest: tuple[dict[str, Any], ...] | None = None,
    review_root: Path | None = None,
) -> list[str]:
    """Compare every privileged/OIDC execution context to the exact reviewed manifest."""

    source_manifest = PRIVILEGED_EXECUTION_MANIFEST if manifest is None else manifest
    expected = {(str(item.get("workflow")), str(item.get("job"))): json.loads(_json(item)) for item in source_manifest}
    try:
        actual = _privileged_jobs(documents)
    except (TypeError, ValueError) as exc:
        return [f"privileged execution manifest mismatch: malformed workflow document: {exc}"]
    errors: list[str] = []
    for key in sorted(actual.keys() - expected.keys()):
        errors.append(f"undeclared privileged execution job: {key[0]}:{key[1]}")
    for key in sorted(expected.keys() - actual.keys()):
        errors.append(f"stale privileged execution job: {key[0]}:{key[1]}")
    for key in sorted(actual.keys() & expected.keys()):
        actual_document = json.loads(_json(asdict(actual[key])))
        if actual_document != expected[key]:
            errors.append(f"privileged execution manifest mismatch: {key[0]}:{key[1]}")

    privileged_workflows = {workflow for workflow, _job in actual}
    for workflow, document in documents.items():
        if workflow not in privileged_workflows:
            continue
        scopes: list[tuple[str, object]] = [(f"{workflow}:workflow", document.get("env"))]
        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict) or (workflow, str(job_name)) not in actual:
                continue
            scopes.append((f"{workflow}:{job_name}:job", job.get("env")))
            container = job.get("container")
            if isinstance(container, dict):
                scopes.append((f"{workflow}:{job_name}:container", container.get("env")))
            for service_name, service in (job.get("services") or {}).items():
                if isinstance(service, dict):
                    scopes.append((f"{workflow}:{job_name}:service-{service_name}", service.get("env")))
            for index, step in enumerate(job.get("steps") or ()):
                if isinstance(step, dict):
                    scopes.append((f"{workflow}:{job_name}:step-{index}", step.get("env")))
        for label, env in scopes:
            if not isinstance(env, dict):
                continue
            for key in env:
                if _dangerous_context_key(key):
                    errors.append(f"dangerous privileged context: {label}:{key}")
    if review_root is not None:
        errors.extend(verify_privileged_review_readiness(review_root, manifest=source_manifest))
    return errors


def verify_privileged_execution_manifest(workflows: Path, rendered_python: dict[str, Any]) -> list[str]:
    return verify_privileged_execution_documents(_documents(workflows, rendered_python))


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else {}


def _documents(workflows: Path, rendered_python: dict[str, Any]) -> dict[str, dict[str, Any]]:
    paths = sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml")))
    documents = {path.name: _load(path) for path in paths}
    documents["rendered-python"] = rendered_python
    return documents


_HEREDOC = re.compile(
    r"(?<!<)<<(?P<tabs>-?)(?!<)(?:'(?P<single>[^']+)'|\"(?P<double>[^\"]+)\"|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))"
)


def _without_heredoc_bodies(script: str) -> str:
    """Remove data bodies so embedded Python/text cannot masquerade as shell."""

    kept: list[str] = []
    delimiter: str | None = None
    strip_tabs = False
    for line in script.splitlines(keepends=True):
        if delimiter is not None:
            candidate = line.rstrip("\r\n")
            if strip_tabs:
                candidate = candidate.lstrip("\t")
            if candidate == delimiter:
                delimiter = None
            continue
        kept.append(line)
        match = _HEREDOC.search(line)
        if match:
            delimiter = match.group("single") or match.group("double") or match.group("bare")
            strip_tabs = match.group("tabs") == "-"
    return "".join(kept)


def _shell_commands(script: str) -> tuple[tuple[str, ...], ...]:
    """Tokenize executable shell command nodes, excluding comments and heredoc data."""

    normalized = _without_heredoc_bodies(script.replace("\\\n", " "))
    commands: list[tuple[str, ...]] = []
    separators = {";", "&", "&&", "|", "||", "(", ")", "{", "}"}
    for line in normalized.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|(){}")
        lexer.whitespace = " \t\r"
        lexer.commenters = "#"
        lexer.wordchars += "/$:-_.=+"
        try:
            tokens = list(lexer)
        except ValueError:
            continue
        current: list[str] = []
        for token in tokens:
            if token in separators:
                if current:
                    commands.append(tuple(current))
                    current = []
            else:
                current.append(token)
        if current:
            commands.append(tuple(current))
    return tuple(commands)


def _program_index(command: tuple[str, ...]) -> int | None:
    index = 0
    while index < len(command) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", command[index]):
        index += 1
    if index < len(command) and command[index] == "command":
        index += 1
    if index < len(command) and Path(command[index]).name == "env":
        index += 1
        while index < len(command) and (command[index].startswith("-") or "=" in command[index]):
            index += 1
    return index if index < len(command) else None


def _command_program(command: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    index = _program_index(command)
    if index is None:
        return "", ()
    return Path(command[index]).name, command[index + 1 :]


def _gh_api_method(arguments: tuple[str, ...]) -> str | None:
    if not arguments or arguments[0] != "api":
        return None
    method = "GET"
    index = 1
    while index < len(arguments):
        token = arguments[index]
        if token in {"-X", "--method"} and index + 1 < len(arguments):
            method = arguments[index + 1].upper()
            index += 2
            continue
        if token.startswith("--method="):
            method = token.split("=", 1)[1].upper()
        elif token.startswith("-X") and len(token) > 2:
            method = token[2:].upper()
        index += 1
    return method


def _mutation_markers(command: tuple[str, ...]) -> tuple[str, ...]:
    program, arguments = _command_program(command)
    joined = " ".join(command)
    if program == "gh":
        method = _gh_api_method(arguments)
        if method and method not in {"GET", "HEAD"}:
            matches = tuple(marker for marker in _GITHUB_API_MARKERS if marker.replace('"', "") in joined)
            return matches or (f"undeclared-gh-api-{method}",)
        if arguments[:2] == ("release", "upload"):
            return ("gh release upload",)
        if arguments[:2] == ("release", "edit"):
            return ("gh release edit",)
    if program == "git" and arguments and arguments[0] == "push":
        return ("git push",)
    if program == "skopeo" and arguments and arguments[0] == "copy":
        return ("skopeo copy",)
    if program == "docker" and arguments[:3] == ("buildx", "imagetools", "create"):
        if "${IMAGE}:latest" in joined:
            return ('imagetools create -t "${IMAGE}:latest"',)
        return ('imagetools create -t "${IMAGE}:${TAG}"',)
    if program == "xcrun" and arguments[:2] == ("altool", "--upload-app"):
        return ("xcrun altool --upload-app",)
    if program == "fastlane" and arguments and arguments[0] == "deliver":
        return ("fastlane deliver",)
    return ()


def is_canonical_verifier_step(step: object) -> bool:
    """Recognize a typed, executable full verifier node; comments never qualify."""

    if not isinstance(step, dict):
        return False
    step_id = str(step.get("id", ""))
    env = step.get("env") or {}
    if not re.fullmatch(r"aviato-verify-[a-z0-9-]+", step_id):
        return False
    if not isinstance(env, dict) or env.get("AVIATO_AUTHORITY_VERIFIER_CONTRACT") != FULL_VERIFIER_CONTRACT:
        return False
    run = str(step.get("run", ""))
    expected_digest = CANONICAL_VERIFIER_RUN_SHA256.get(step_id)
    if expected_digest is None or hashlib.sha256(run.encode("utf-8")).hexdigest() != expected_digest:
        return False
    for command in _shell_commands(run):
        program, arguments = _command_program(command)
        if program == "python3" and "-I" in arguments:
            index = _program_index(command)
            if (
                index is not None
                and "env" in {Path(token).name for token in command[:index]}
                and "-i" in command[:index]
            ):
                return True
    return False


def discover_hosted_mutations(workflows: Path, rendered_python: dict[str, Any]) -> tuple[HostedMutation, ...]:
    """Reverse-discover every known hosted mutation class from workflow structure."""

    found: list[HostedMutation] = []
    for workflow_name, document in _documents(workflows, rendered_python).items():
        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or ():
                if not isinstance(step, dict):
                    continue
                step_name = str(step.get("name", ""))
                uses = str(step.get("uses", "")).split("@", 1)[0]
                if uses in _ACTION_KINDS:
                    found.append(HostedMutation(workflow_name, str(job_name), step_name, uses, _ACTION_KINDS[uses]))
                script = str(step.get("run", ""))
                for command in _shell_commands(script):
                    for marker in _mutation_markers(command):
                        found.append(HostedMutation(workflow_name, str(job_name), step_name, marker))
    return tuple(found)


def _guard_errors(mutation: HostedMutation, document: dict[str, Any]) -> list[str]:
    job = (document.get("jobs") or {}).get(mutation.job) or {}
    steps = job.get("steps") or []
    matches = [
        (index, step)
        for index, step in enumerate(steps)
        if isinstance(step, dict) and step.get("name") == mutation.step
    ]
    label = ":".join(mutation.identity)
    if len(matches) != 1:
        return [f"{label}: stale declared mutation step is absent or ambiguous"]
    index, step = matches[0]
    if mutation.boundary == "fixed-artifact-attestation":
        expected_permissions = {"contents": "read", "id-token": "write", "attestations": "write"}
        expected_names = ["Download only verified artifact", "Attest fixed verified artifact"]
        if (
            job.get("permissions") != expected_permissions
            or [candidate.get("name") for candidate in steps] != expected_names
        ):
            return [f"{label}: fixed verified-artifact trust edge changed"]
        if mutation.marker != str(step.get("uses", "")).split("@", 1)[0]:
            return [f"{label}: fixed verified-artifact attestation action changed"]
        return []
    if mutation.kind in {"action", "oidc-attestation"}:
        if mutation.marker != str(step.get("uses", "")).split("@", 1)[0]:
            return [f"{label}: declared action marker is absent"]
        if (
            mutation.workflow == "reusable-docker-ghcr.yml"
            and (step.get("with") or {}).get("push-to-registry") is not True
        ):
            return [f"{label}: registry attestation must bind the published registry subject"]
    elif mutation.marker not in {
        marker for command in _shell_commands(str(step.get("run", ""))) for marker in _mutation_markers(command)
    }:
        return [f"{label}: declared shell marker is absent"]

    if mutation.kind in {"action", "oidc-attestation"}:
        previous = steps[index - 1] if index else {}
        if not is_canonical_verifier_step(previous):
            return [f"{label}: immediately preceding canonical verifier is absent"]
        if mutation.verifier_step_id and previous.get("id") != mutation.verifier_step_id:
            return [f"{label}: canonical verifier step id does not match the manifest"]
        return []

    if mutation.boundary == "isolated-attestation":
        encoded = yaml.safe_dump(job)
        forbidden = ("actions/checkout", "eval ", "xcodebuild", "npm ", "pip install")
        if any(command in encoded for command in forbidden):
            return [f"{label}: isolated attestation job can execute consumer content"]
        return []
    if mutation.boundary == "job-authority":
        earlier = "\n".join(str(candidate.get("run", "")) for candidate in steps[:index] if isinstance(candidate, dict))
        if (
            "Recheck managed checkpoint before OIDC" not in str([candidate.get("name") for candidate in steps[:index]])
            or "gh attestation verify" not in earlier
        ):
            return [f"{label}: OIDC attestation lacks an earlier authority check"]
        return []
    if mutation.boundary == "authority-job":
        needs = job.get("needs") or ()
        needed = {needs} if isinstance(needs, str) else set(needs)
        condition = str(job.get("if", ""))
        if "authority" not in needed or "needs.authority.outputs.authorized == 'true'" not in condition:
            return [f"{label}: write job is not dominated by the authority job"]
        return []
    if mutation.boundary == "status-bridge":
        if job.get("permissions") != {"statuses": "write"} or "${{ github.token }}" not in yaml.safe_dump(job):
            return [f"{label}: status mutation lacks its narrow generated status-bridge boundary"]
        return []
    if mutation.boundary == "preceding-verifier":
        previous = steps[index - 1] if index else {}
        if not is_canonical_verifier_step(previous):
            return [f"{label}: immediately preceding canonical verifier is absent"]
        return []

    commands = _shell_commands(str(step.get("run", "")))
    mutation_indexes = [i for i, command in enumerate(commands) if mutation.marker in _mutation_markers(command)]
    if len(mutation_indexes) != 1:
        return [f"{label}: structural mutation command is absent or ambiguous"]
    mutation_index = mutation_indexes[0]
    if mutation_index == 0:
        return [f"{label}: mutation is not dominated by an executable verifier call"]
    expected = mutation.guard_call or "aviato_verify_authority"
    program, _arguments = _command_program(commands[mutation_index - 1])
    return (
        [] if program == expected else [f"{label}: executable verifier invocation is not immediately before mutation"]
    )


def verify_mutation_inventory(
    workflows: Path,
    rendered_python: dict[str, Any],
    *,
    manifest: tuple[HostedMutation, ...] = HOSTED_MUTATIONS,
) -> list[str]:
    """Require a one-to-one manifest/discovery mapping, then verify dominance."""

    discovered = discover_hosted_mutations(workflows, rendered_python)
    declared_counts = Counter(item.identity for item in manifest)
    discovered_counts = Counter(item.identity for item in discovered)
    errors = verify_privileged_execution_documents(_documents(workflows, rendered_python))
    for identity, count in sorted((discovered_counts - declared_counts).items()):
        errors.append(f"undeclared hosted mutation: {':'.join(identity)} ({count})")
    for identity, count in sorted((declared_counts - discovered_counts).items()):
        errors.append(f"stale declared mutation: {':'.join(identity)} ({count})")
    documents = _documents(workflows, rendered_python)
    for mutation in manifest:
        document = documents.get(mutation.workflow)
        if document is not None:
            errors.extend(_guard_errors(mutation, document))
    return errors
