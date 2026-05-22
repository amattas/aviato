from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .marker import parse_marker_from_text, strip_marker_from_text

BASELINE_REMOVAL_WARNING = (
    "Offboarding removes the always-on security baseline (§2.13) and all Aviato "
    "protection from this repository. This is the maximal protection reduction; "
    "review carefully before merging."
)


@dataclass
class OffboardingResult:
    stripped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    declaration_removed: bool = False
    sidecar_removed: bool = False
    warning: str = BASELINE_REMOVAL_WARNING


def offboard(root: Path, managed_outputs: Sequence[str], *, keep_files: bool) -> OffboardingResult:
    """Remove a Consumer from Aviato management (§5.13).

    Either strip managed markers (converting managed files to plain
    operator-owned files) or delete them, per ``keep_files``; then delete the
    declaration and the seed-once sidecar. The result carries the §2.13 baseline
    removal warning. Only files that currently carry a valid marker are touched;
    operator-owned/unmanaged files are left as-is.
    """
    root = Path(root)
    result = OffboardingResult()

    for output in managed_outputs:
        target = root / output
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        if parse_marker_from_text(text) is None:
            continue  # unmanaged / malformed — operator owns it, leave alone
        if keep_files:
            target.write_text(strip_marker_from_text(text), encoding="utf-8")
            result.stripped.append(output)
        else:
            target.unlink()
            result.removed.append(output)

    declaration = root / ".github" / "aviato.yaml"
    if declaration.is_file():
        declaration.unlink()
        result.declaration_removed = True

    sidecar = root / ".github" / "aviato.seed.json"
    if sidecar.is_file():
        sidecar.unlink()
        result.sidecar_removed = True

    return result
