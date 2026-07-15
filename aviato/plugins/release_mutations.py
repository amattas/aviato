"""Bijective inventory of hosted mutations and OIDC attestations."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections import Counter
from dataclasses import asdict, dataclass
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
    "/aviato/library/privileged-review-attestation.json",
    "/aviato/library/privileged-review-policy.json",
    "/aviato/library/policy.yml",
    "/aviato/library/rulesets/protect-default-branch.json",
    "/aviato/plugins/release_mutations.py",
    "/scripts/regen-privileged-execution-manifest.py",
)


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

    if not isinstance(policy.get("minimum_approvals"), int) or policy["minimum_approvals"] < 2:
        errors.append("protected review policy must require at least two approvals")
    for key in ("require_non_author", "require_code_owner_review", "require_last_push_approval"):
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

    expected_hashes = {
        "candidate_manifest_sha256": privileged_manifest_sha256(manifest),
        "policy_sha256": _file_sha256(policy_path),
        "codeowners_sha256": _file_sha256(codeowners_path),
    }
    if record.get("schema_version") != 1:
        errors.append("protected review record has an unsupported schema_version")
    if record.get("status") not in {"pending", "approved"}:
        errors.append("protected review record status must be pending or approved")
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


def verify_packaged_privileged_review_readiness(data_root: Path) -> list[str]:
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
    errors: list[str] = []
    if record.get("candidate_manifest_sha256") != privileged_manifest_sha256(manifest):
        errors.append("protected review package attestation does not bind its privileged manifest")
    if record.get("policy_sha256") != _file_sha256(policy_path):
        errors.append("protected review package attestation does not bind its review policy")
    codeowners_hash = record.get("codeowners_sha256")
    if not isinstance(codeowners_hash, str) or re.fullmatch(r"[0-9a-f]{64}", codeowners_hash) is None:
        errors.append("protected review package attestation lacks a valid CODEOWNERS identity")
    if record.get("status") != "approved":
        errors.append("protected review is pending: configure reviewer/team IDs and record protected approvals")
        return errors
    minimum = policy.get("minimum_approvals")
    reviewer_ids = policy.get("reviewer_database_ids")
    team_ids = policy.get("team_database_ids")
    author_id = record.get("author_database_id")
    approvals = record.get("approvals")
    if not isinstance(minimum, int) or minimum < 2:
        errors.append("protected review package policy must require at least two approvals")
        return errors
    if not isinstance(reviewer_ids, list) or not isinstance(team_ids, list):
        errors.append("protected review package reviewer/team database IDs must be lists")
        return errors
    if not reviewer_ids and not team_ids:
        errors.append("protected review has no configured reviewer or team database IDs")
    if isinstance(author_id, bool) or not isinstance(author_id, int) or author_id <= 0:
        errors.append("protected review package attestation requires a positive author_database_id")
    if not isinstance(approvals, list):
        errors.append("protected review package approvals must be a list")
        return errors
    approved_reviewers: set[int] = set()
    for approval in approvals:
        if not isinstance(approval, dict):
            errors.append("protected review package approval entries must be mappings")
            continue
        reviewer_id = approval.get("reviewer_database_id")
        review_id = approval.get("review_id")
        if isinstance(reviewer_id, bool) or not isinstance(reviewer_id, int) or reviewer_id <= 0:
            errors.append("protected review package approval requires a positive reviewer_database_id")
            continue
        if isinstance(review_id, bool) or not isinstance(review_id, int) or review_id <= 0:
            errors.append("protected review package approval requires a positive immutable review_id")
        if reviewer_id == author_id:
            errors.append("protected review package approval must be from a non-author")
        team_id = approval.get("team_database_id")
        if reviewer_id not in reviewer_ids and team_id not in team_ids:
            errors.append("protected review package approval is not bound to a configured reviewer or team database ID")
        approved_reviewers.add(reviewer_id)
    if len(approved_reviewers) < minimum:
        errors.append(f"protected review requires {minimum} distinct recorded approving reviewers")
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
    serialized = _json(job).lower()
    if "secrets." in serialized or "secrets:inherit" in serialized or "github.token" in serialized:
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
        top_permissions = document.get("permissions") or {}
        jobs = document.get("jobs") or {}
        selected: set[str] = set()
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            permissions = job.get("permissions") if "permissions" in job else top_permissions
            if isinstance(permissions, dict) and _trust_sensitive_seed(workflow, str(job_name), job, permissions):
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
            if not isinstance(permissions, dict):
                permissions = {}
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
    actual = _privileged_jobs(documents)
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
