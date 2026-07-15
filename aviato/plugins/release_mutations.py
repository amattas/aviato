"""Bijective inventory of hosted mutations and OIDC attestations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

SECURE_VERIFIER_MARKER = "AVIATO_SECURE_VERIFIER_BOOTSTRAP"
ActionKind = Literal["shell", "action", "oidc-attestation"]


@dataclass(frozen=True)
class HostedMutation:
    workflow: str
    job: str
    step: str
    marker: str
    kind: ActionKind = "shell"
    guard_call: str | None = None
    boundary: Literal[
        "same-step",
        "preceding-verifier",
        "job-authority",
        "authority-job",
        "isolated-attestation",
        "status-bridge",
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
        boundary="job-authority",
    ),
    HostedMutation(
        "rendered-python",
        "pypi-publish",
        "Attest SBOM",
        "actions/attest-sbom",
        "oidc-attestation",
        boundary="job-authority",
    ),
    HostedMutation(
        "rendered-python",
        "pypi-publish",
        "Publish distributions",
        "pypa/gh-action-pypi-publish",
        "action",
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
        boundary="preceding-verifier",
    ),
    HostedMutation(
        "aviato-ci.yml",
        "pypi-publish",
        "Attest build provenance",
        "actions/attest-build-provenance",
        "oidc-attestation",
        boundary="job-authority",
    ),
    HostedMutation(
        "aviato-ci.yml",
        "pypi-publish",
        "Attest SBOM",
        "actions/attest-sbom",
        "oidc-attestation",
        boundary="job-authority",
    ),
    HostedMutation(
        "aviato-ci.yml",
        "pypi-publish",
        "Publish distributions",
        "pypa/gh-action-pypi-publish",
        "action",
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
        boundary="preceding-verifier",
    ),
    HostedMutation(
        "aviato-protection-checkpoint.yml",
        "attest",
        "Attest fixed verified artifact",
        "actions/attest-build-provenance",
        "oidc-attestation",
        boundary="isolated-attestation",
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
        "docker",
        "Attest published image provenance",
        "actions/attest-build-provenance",
        "oidc-attestation",
        boundary="preceding-verifier",
    ),
    HostedMutation(
        "reusable-docker-ghcr.yml",
        "docker",
        "Tag and push latest (monotonic guard)",
        'imagetools create -t "${IMAGE}:latest"',
    ),
    HostedMutation(
        "reusable-app-store-connect.yml",
        "attest-unsigned",
        "Attest unsigned archive provenance",
        "actions/attest-build-provenance",
        "oidc-attestation",
        boundary="isolated-attestation",
    ),
    HostedMutation(
        "reusable-app-store-connect.yml",
        "app-store-connect",
        "Upload to App Store Connect",
        "xcrun altool --upload-app",
    ),
    HostedMutation(
        "reusable-app-store-connect.yml", "app-store-connect", "Submit for review (built-in)", "fastlane deliver"
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
_SHELL_MARKERS = (
    "gh release upload",
    "gh release edit",
    "git push",
    "skopeo copy",
    'imagetools create -t "${IMAGE}:${TAG}"',
    'imagetools create -t "${IMAGE}:latest"',
    "xcrun altool --upload-app",
    "fastlane deliver",
)
_GITHUB_API_MARKERS = (
    'git/refs" -f ref="refs/tags/${NEXT}',
    "git/refs/tags/${major}",
    'git/refs" -f ref="refs/tags/${major}',
    'repos/${GITHUB_REPOSITORY}/releases"',
    "statuses/${GITHUB_SHA}",
)


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else {}


def _documents(workflows: Path, rendered_python: dict[str, Any]) -> dict[str, dict[str, Any]]:
    documents = {path.name: _load(path) for path in sorted(workflows.glob("*.yml"))}
    documents["rendered-python"] = rendered_python
    return documents


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
                for marker in _SHELL_MARKERS:
                    if marker in script:
                        found.append(HostedMutation(workflow_name, str(job_name), step_name, marker))
                for line in script.splitlines():
                    if "gh api" not in line or not any(
                        token in line
                        for token in ("--method POST", "--method PATCH", "--method PUT", "--method DELETE")
                    ):
                        continue
                    matches = [marker for marker in _GITHUB_API_MARKERS if marker in line]
                    if len(matches) == 1:
                        found.append(HostedMutation(workflow_name, str(job_name), step_name, matches[0]))
                    else:
                        method = next(
                            token.rsplit(" ", 1)[-1]
                            for token in ("--method POST", "--method PATCH", "--method PUT", "--method DELETE")
                            if token in line
                        )
                        found.append(
                            HostedMutation(workflow_name, str(job_name), step_name, f"undeclared-gh-api-{method}")
                        )
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
    if mutation.kind in {"action", "oidc-attestation"}:
        if mutation.marker not in str(step.get("uses", "")):
            return [f"{label}: declared action marker is absent"]
        if (
            mutation.workflow == "reusable-docker-ghcr.yml"
            and (step.get("with") or {}).get("push-to-registry") is not True
        ):
            return [f"{label}: registry attestation must bind the published registry subject"]
    elif mutation.marker not in str(step.get("run", "")):
        return [f"{label}: declared shell marker is absent"]

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
        script = str(previous.get("run", ""))
        if SECURE_VERIFIER_MARKER not in script or "/usr/bin/python3 -I" not in script:
            return [f"{label}: immediately preceding executable verifier is absent"]
        return []

    script = str(step.get("run", ""))
    position = script.find(mutation.marker)
    verifier = script.rfind(SECURE_VERIFIER_MARKER, 0, position)
    if verifier < 0:
        return [f"{label}: mutation is not dominated by the secure verifier"]
    region = script[verifier:position]
    guarded = mutation.guard_call in region if mutation.guard_call else "/usr/bin/python3 -I" in region
    return [] if guarded else [f"{label}: executable verifier invocation is absent before mutation"]


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
    errors: list[str] = []
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
