from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .errors import BootstrapError
from .marker import content_hash, parse_marker_from_text
from .scaffold import read_sidecar
from .version import is_known_version_pin

ArtifactStatus = Literal["clean", "mergeable-drift", "dirty-drift", "missing"]


@dataclass(frozen=True)
class ExpectedArtifact:
    output_path: str
    body: str
    seed_once: bool = False


@dataclass
class DiagnosisReport:
    statuses: dict[str, ArtifactStatus] = field(default_factory=dict)
    seed_divergence: list[str] = field(default_factory=list)
    secret_in_declaration: bool = False
    # §5.4 probes. Locally-determinable ones are filled by diagnose(); the
    # platform-dependent ones (issue-channel availability, per-run scan heartbeat)
    # are left None here and populated by the GitHub binding when it has API access
    # — and absence reads as broken, never clean (§5.14).
    drift_automation_present: bool = False
    prerequisites: dict[str, bool] = field(default_factory=dict)
    issue_channel_available: bool | None = None
    scan_heartbeat_present: bool | None = None


def _has_drift_automation(root: Path) -> bool:
    """True if a consumer workflow wires the scheduled drift/report automation (§5.5/§5.6)."""
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return False
    # errors="replace": a corrupted/non-UTF-8 workflow file must not crash diagnosis (and
    # thus a whole fleet scan); the check is a substring search, so replacement is harmless.
    return any(
        "reusable-consumer-automation" in path.read_text(encoding="utf-8", errors="replace")
        for path in workflows.glob("*.yml")
    )


def _probe_prerequisites(root: Path, prerequisite_paths: Mapping[str, Sequence[str]]) -> dict[str, bool]:
    """Probe the §17 prerequisites determinable from the local tree.

    The names and candidate paths are plug-in **data** (e.g. a service profile
    declares its container build definition), never hardcoded here — so the core
    stays free of deployment-specific identifiers (§9b). A prerequisite is
    satisfied if any of its candidate paths exists.
    """
    return {
        name: any((root / candidate).is_file() for candidate in candidates)
        for name, candidates in prerequisite_paths.items()
    }


def _live_body(text: str) -> str:
    """Return the file body with its marker (first non-blank line) removed."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip():
            return "".join(lines[i + 1 :])
    return ""


def _classify_managed(target: Path, expected_body: str) -> ArtifactStatus:
    if not target.exists():
        return "missing"
    text = target.read_text(encoding="utf-8")
    marker = parse_marker_from_text(text)
    if marker is None:
        # No marker, or malformed marker → never silently regenerated (§5.4).
        return "dirty-drift"
    if not is_known_version_pin(marker.version):
        # Recorded version unknown/unparseable → dirty-drift: compatibility cannot be
        # established, so the file is never silently regenerated over (§5.4).
        return "dirty-drift"
    live = content_hash(_live_body(text))
    expected = content_hash(expected_body)
    # Clean only when the body matches expected AND the marker hash is current — so
    # diagnosis and scaffold agree on the same file (a stale marker is regenerable,
    # not clean). The marker version is excluded (§5.5), so a version-only move stays
    # clean.
    if live == expected and marker.hash == live:
        return "clean"
    # The marker records the hash of the body Aviato last wrote. If the live body
    # still matches it (template/variable moved) OR already matches expected (only the
    # marker is stale), regenerating is safe → mergeable. If it matches neither, the
    # operator hand-edited a managed file → dirty-drift, never silently clobbered
    # (§5.4, §2.5).
    if live == marker.hash or live == expected:
        return "mergeable-drift"
    return "dirty-drift"


def diagnose(
    root: Path,
    expected: Sequence[ExpectedArtifact],
    *,
    declaration_variables: Mapping[str, object] | None = None,
    secret_var_names: Sequence[str] = (),
    prerequisite_paths: Mapping[str, Sequence[str]] | None = None,
    is_library: bool = False,
    bootstrap_declared: bool = False,
) -> DiagnosisReport:
    """Classify a Consumer's managed artifacts and probe its health (§5.4).

    Reject a bootstrap declaration in any repository that is not the Library
    (§5.10). For each expected managed artifact, classify clean / mergeable-drift
    / dirty-drift / missing, comparing bodies with the marker version excluded
    (§5.5). Seed-once files are compared to their report-only sidecar hash and
    divergence is reported, never overwritten (§6.3). Any secret-typed variable
    present in the declaration is flagged (§6.6/§8.15).
    """
    if bootstrap_declared and not is_library:
        raise BootstrapError("a bootstrap declaration is only valid in the Library (§5.10)")

    root = Path(root)
    report = DiagnosisReport()
    sidecar = read_sidecar(root)

    for artifact in expected:
        target = root / artifact.output_path
        if artifact.seed_once:
            recorded = sidecar.get(artifact.output_path)
            if (
                target.exists()
                and recorded is not None
                and content_hash(target.read_text(encoding="utf-8")) != recorded
            ):
                report.seed_divergence.append(artifact.output_path)
            continue
        report.statuses[artifact.output_path] = _classify_managed(target, artifact.body)

    declaration_variables = declaration_variables or {}
    report.secret_in_declaration = any(name in declaration_variables for name in secret_var_names)

    report.drift_automation_present = _has_drift_automation(root)
    report.prerequisites = _probe_prerequisites(root, prerequisite_paths or {})

    return report
