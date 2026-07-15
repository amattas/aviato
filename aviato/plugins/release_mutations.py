"""Typed inventory of checkpoint-authorized hosted release mutations.

The inventory makes the security boundary reviewable and machine checked.  A
shell-hosted mutation must carry the in-memory verifier bootstrap in the same
step immediately before its command.  Action-hosted mutations must be
immediately preceded by a verifier step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

SECURE_VERIFIER_MARKER = "AVIATO_SECURE_VERIFIER_BOOTSTRAP"


@dataclass(frozen=True)
class HostedMutation:
    workflow: str
    job: str
    step: str
    marker: str
    mode: Literal["run", "uses"] = "run"
    guard_call: str | None = None


HOSTED_MUTATIONS: tuple[HostedMutation, ...] = (
    HostedMutation("rendered-python", "pypi-publish", "Publish distributions", "pypa/gh-action-pypi-publish", "uses"),
    HostedMutation(
        "rendered-python",
        "pypi-publish",
        "Publish distributions to alternate repository",
        "pypa/gh-action-pypi-publish",
        "uses",
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
        "Tag and push latest (monotonic guard)",
        'imagetools create -t "${IMAGE}:latest"',
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
    HostedMutation("reusable-docs-pages.yml", "push", "Verify and fast-forward push", "git push origin"),
    HostedMutation("reusable-docs-pages.yml", "deploy", "Deploy GitHub Pages", "actions/deploy-pages", "uses"),
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
        "--method PATCH",
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


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else {}


def verify_mutation_inventory(workflows: Path, rendered_python: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cache: dict[str, dict[str, Any]] = {"rendered-python": rendered_python}
    for mutation in HOSTED_MUTATIONS:
        if mutation.workflow not in cache:
            cache[mutation.workflow] = _load(workflows / mutation.workflow)
        document = cache[mutation.workflow]
        job = (document.get("jobs") or {}).get(mutation.job) or {}
        steps = job.get("steps") or []
        matches = [
            (index, step)
            for index, step in enumerate(steps)
            if isinstance(step, dict) and step.get("name") == mutation.step
        ]
        label = f"{mutation.workflow}:{mutation.job}:{mutation.step}:{mutation.marker}"
        if len(matches) != 1:
            errors.append(f"{label}: step is absent or ambiguous")
            continue
        index, step = matches[0]
        if mutation.mode == "uses":
            if mutation.marker not in str(step.get("uses", "")):
                errors.append(f"{label}: action mutation marker is absent")
                continue
            previous = steps[index - 1] if index else {}
            previous_script = str(previous.get("run", ""))
            if SECURE_VERIFIER_MARKER not in previous_script or "/usr/bin/python3 -I" not in previous_script:
                errors.append(f"{label}: immediately preceding verifier is absent")
            continue
        script = str(step.get("run", ""))
        positions = [offset for offset in range(len(script)) if script.startswith(mutation.marker, offset)]
        if not positions:
            errors.append(f"{label}: mutation marker is absent")
            continue
        for position in positions:
            verifier = script.rfind(SECURE_VERIFIER_MARKER, 0, position)
            if verifier < 0:
                errors.append(f"{label}: mutation is not dominated by the secure verifier")
                break
            guarded_region = script[verifier:position]
            if mutation.guard_call is None:
                guarded = "/usr/bin/python3 -I" in guarded_region
            else:
                # The region begins at the marker inside the function, after
                # its declaration, so a later occurrence proves invocation.
                guarded = mutation.guard_call in guarded_region
            if not guarded:
                errors.append(f"{label}: executable verifier invocation is absent before mutation")
                break
    return errors
