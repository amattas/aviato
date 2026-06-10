from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .bootstrap import is_library
from .composition import resolve_profile
from .declaration import Declaration, load_declaration
from .diagnosis import ExpectedArtifact, diagnose
from .errors import AviatoError
from .onboarding import resolved_artifacts
from .registry import Registry


@dataclass
class RepoScan:
    path: str
    profile: str | None = None
    statuses: dict[str, str] = field(default_factory=dict)
    seed_divergence: list[str] = field(default_factory=list)
    secret_in_declaration: bool = False
    # finding 33: §5.11 says "run diagnosis (§5.4)" — the fleet sweep previously omitted
    # the §17 prerequisite and drift-automation probes doctor passes, so a fleet-wide
    # missing-prerequisite / missing-drift-workflow condition was invisible at scale.
    prerequisites: dict[str, bool] = field(default_factory=dict)
    drift_automation_present: bool | None = None
    error: str | None = None
    # True when the repo was skipped because it is archived and --include-archived was not
    # passed (§5.11). Distinct from ``error`` (it is a deliberate skip, not a failure).
    skipped_archived: bool = False


def _expected_artifacts(registry: Registry, declaration: Declaration) -> list[ExpectedArtifact]:
    # Same resolution/rendering/conditional-filtering (pin, docs, variant) as
    # onboarding/doctor — so the fleet scan doesn't report false drift for
    # variant-excluded consumers or miss docs-enabled artifacts (§5.11 parity).
    return [
        ExpectedArtifact(a.output, a.body if not a.seed_once else "", a.seed_once)
        for a in resolved_artifacts(
            registry,
            declaration.profile,
            declaration.variables,
            pin=declaration.version,
            docs=declaration.docs,
            bootstrap=declaration.bootstrap,
            overrides=declaration.overrides,
        )
    ]


def scan_fleet(
    paths: Sequence[Path],
    registry: Registry,
    *,
    include_archived: bool = False,
    archived_probe: Callable[[Path], bool | None] | None = None,
    drift_automation_markers: Sequence[str] = (),
) -> list[RepoScan]:
    """Run §5.4 diagnosis across many local repositories, read-only (§5.11).

    The repository list is resolved by the operator (here, explicit paths) — never
    a Library-held registry (§2.2). Each repo is diagnosed independently; a repo
    without a declaration is reported as an error rather than crashing the scan.
    Nothing is mutated and no proposal is opened (that is ``scan --fix``, layered
    on :func:`aviato.core.file_drift_flow.run_file_drift`).

    **Archived repos are skipped unless ``include_archived``** (§5.11). Whether a repo
    is archived is a platform attribute, so the check is supplied by an injected
    ``archived_probe`` (the binding lives outside core, §2.14); the probe returning
    ``None`` (unknown — e.g. no remote / offline) is treated as *not* archived, so a
    repo is never silently dropped from the operator's read-only scan on an ambiguous read.
    """
    scans: list[RepoScan] = []
    for path in paths:
        root = Path(path)
        if not include_archived and archived_probe is not None and archived_probe(root) is True:
            scans.append(RepoScan(path=str(root), skipped_archived=True))
            continue
        declaration_path = root / ".github" / "aviato.yaml"
        if not declaration_path.is_file():
            scans.append(RepoScan(path=str(root), error="no declaration"))
            continue
        try:
            declaration = load_declaration(declaration_path)
            expected = _expected_artifacts(registry, declaration)
            resolved = resolve_profile(registry, declaration.profile, docs=declaration.docs)
            secret_names = tuple(spec.name for spec in resolved.variables if spec.secret)
            report = diagnose(
                root,
                expected,
                declaration_variables=declaration.variables,
                secret_var_names=secret_names,
                # finding 33: full §5.4 parity with doctor — prerequisites come from the
                # profile's plug-in data; the drift markers are Library artifact names
                # the CLI supplies (core never hardcodes them, review #18).
                prerequisite_paths=registry.profile_doc(declaration.profile).get("prerequisites", {}),
                drift_automation_markers=drift_automation_markers,
                profile=declaration.profile,
                is_library=is_library(root),
                bootstrap_declared=declaration.bootstrap,
            )
        except AviatoError as exc:
            scans.append(RepoScan(path=str(root), error=str(exc)))
            continue
        scans.append(
            RepoScan(
                path=str(root),
                profile=declaration.profile,
                statuses=dict[str, str](report.statuses),
                seed_divergence=report.seed_divergence,
                secret_in_declaration=report.secret_in_declaration,
                prerequisites=dict(report.prerequisites),
                drift_automation_present=report.drift_automation_present if drift_automation_markers else None,
            )
        )
    return scans
