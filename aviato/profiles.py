from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProfilePlan:
    name: str
    templates: tuple[str, ...]
    secrets: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


PROFILES: dict[str, ProfilePlan] = {
    "python-service": ProfilePlan(
        name="python-service",
        templates=("templates/profile-python-service.yml",),
        notes=("Requires a Dockerfile before GHCR release publishing can run.",),
    ),
    "python-library": ProfilePlan(
        name="python-library",
        templates=("templates/profile-python-library.yml",),
        notes=("Requires PyPI trusted publishing registration for the caller workflow.",),
    ),
    "node-service": ProfilePlan(
        name="node-service",
        templates=("templates/profile-node-service.yml",),
        notes=("Requires a Dockerfile before GHCR release publishing can run.",),
    ),
    "swift-app": ProfilePlan(
        name="swift-app",
        templates=("templates/profile-swift-app.yml",),
        secrets=(
            "APP_STORE_CONNECT_ISSUER_ID",
            "APP_STORE_CONNECT_KEY_ID",
            "APP_STORE_CONNECT_API_PRIVATE_KEY",
            "APPLE_CERTIFICATE_P12_BASE64",
            "APPLE_CERTIFICATE_PASSWORD",
            "APPLE_PROVISIONING_PROFILE_BASE64",
        ),
        environments=("app-store-connect",),
        notes=(
            "The app-store-connect environment should require reviewers.",
            "Replace placeholder scheme, workspace, bundle identifier, team ID, and export options values.",
        ),
    ),
}


def profile_plan(name: str) -> ProfilePlan:
    try:
        return PROFILES[name]
    except KeyError as exc:
        available = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown profile {name!r}; available profiles: {available}") from exc
