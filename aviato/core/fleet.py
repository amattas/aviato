from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .composition import resolve_profile
from .declaration import load_declaration
from .diagnosis import ExpectedArtifact, diagnose
from .errors import AviatoError
from .registry import Registry
from .render import render


@dataclass
class RepoScan:
    path: str
    profile: str | None = None
    statuses: dict[str, str] = field(default_factory=dict)
    seed_divergence: list[str] = field(default_factory=list)
    secret_in_declaration: bool = False
    error: str | None = None


def _expected_artifacts(registry: Registry, profile: str, variables: Mapping[str, Any]) -> list[ExpectedArtifact]:
    resolved = resolve_profile(registry, profile)
    artifacts: list[ExpectedArtifact] = []
    for template in resolved.templates:
        body = registry.template_body(template)
        rendered = "" if template.seed_once else render(body, variables)
        artifacts.append(ExpectedArtifact(template.output_path, rendered, template.seed_once))
    return artifacts


def scan_fleet(paths: Sequence[Path], registry: Registry) -> list[RepoScan]:
    """Run §5.4 diagnosis across many local repositories, read-only (§5.11).

    The repository list is resolved by the operator (here, explicit paths) — never
    a Library-held registry (§2.2). Each repo is diagnosed independently; a repo
    without a declaration is reported as an error rather than crashing the scan.
    Nothing is mutated and no proposal is opened (that is ``scan --fix``, layered
    on :func:`aviato.core.file_drift_flow.run_file_drift`).
    """
    scans: list[RepoScan] = []
    for path in paths:
        root = Path(path)
        declaration_path = root / ".github" / "aviato.yaml"
        if not declaration_path.is_file():
            scans.append(RepoScan(path=str(root), error="no declaration"))
            continue
        try:
            declaration = load_declaration(declaration_path)
            expected = _expected_artifacts(registry, declaration.profile, declaration.variables)
            resolved = resolve_profile(registry, declaration.profile)
            secret_names = tuple(spec.name for spec in resolved.variables if spec.secret)
            report = diagnose(
                root,
                expected,
                declaration_variables=declaration.variables,
                secret_var_names=secret_names,
            )
        except AviatoError as exc:
            scans.append(RepoScan(path=str(root), error=str(exc)))
            continue
        scans.append(
            RepoScan(
                path=str(root),
                profile=declaration.profile,
                statuses=report.statuses,
                seed_divergence=report.seed_divergence,
                secret_in_declaration=report.secret_in_declaration,
            )
        )
    return scans
