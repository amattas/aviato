from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .errors import BootstrapError
from .marker import content_hash, parse_marker_from_text
from .scaffold import read_sidecar

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
    if content_hash(_live_body(text)) == content_hash(expected_body):
        return "clean"
    return "mergeable-drift"


def diagnose(
    root: Path,
    expected: Sequence[ExpectedArtifact],
    *,
    declaration_variables: Mapping[str, object] | None = None,
    secret_var_names: Sequence[str] = (),
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
            if target.exists() and recorded is not None:
                if content_hash(target.read_text(encoding="utf-8")) != recorded:
                    report.seed_divergence.append(artifact.output_path)
            continue
        report.statuses[artifact.output_path] = _classify_managed(target, artifact.body)

    declaration_variables = declaration_variables or {}
    report.secret_in_declaration = any(name in declaration_variables for name in secret_var_names)

    return report
