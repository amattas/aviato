from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .errors import AviatoError
from .marker import parse_marker_from_text, strip_marker_from_text
from .pathguard import confined_target
from .scaffold import atomic_write

BASELINE_REMOVAL_WARNING = (
    "Offboarding removes the always-on security baseline (§2.13) automation and stops "
    "Aviato from maintaining this repository's protection. Note: any branch protection "
    "and rulesets Aviato applied remain on GitHub but become UNMANAGED — this command "
    "does not tear them down; remove them manually if you want protection fully removed. "
    "This is the maximal protection reduction; review carefully before merging."
)


@dataclass
class OffboardingResult:
    stripped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    declaration_removed: bool = False
    sidecar_removed: bool = False
    warning: str = BASELINE_REMOVAL_WARNING


def _is_consumer_automation(output: str) -> bool:
    """True for a managed file GitHub auto-executes — a workflow under
    ``.github/workflows/``.

    Such a file keeps running if only its marker is stripped (GitHub runs every
    workflow in that directory regardless of any comment). So §5.13's distinct
    "remove the consumer automation (the scheduled drift/report workflows)" step
    requires **deleting** these, even when the operator chose to keep managed files
    as plain operator-owned files. Passive managed configs (lint/format settings)
    follow the keep-files choice as before. The boundary is platform-structural —
    the same ``.github`` location this module already uses for the declaration —
    not a language/tool specific (§9b) identifier.
    """
    parts = Path(output).parts
    return len(parts) >= 2 and parts[0] == ".github" and parts[1] == "workflows"


def offboard(root: Path, managed_outputs: Sequence[str], *, keep_files: bool) -> OffboardingResult:
    """Remove a Consumer from Aviato management (§5.13).

    For passive managed files (lint/format configs), either strip managed markers
    (converting them to plain operator-owned files) or delete them, per
    ``keep_files``. The **consumer automation** caller workflows
    (``.github/workflows/*``) are always deleted regardless of ``keep_files`` — a
    marker-stripped-but-present workflow would keep running, so stripping alone does
    not stop the §2.13 baseline / drift automation the warning says it removes.
    Then delete the declaration and the seed-once sidecar. The result carries the
    §2.13 baseline removal warning. Only files that currently carry a valid marker
    are touched; operator-owned/unmanaged files are left as-is.

    Marker parsing/classification happens up front so a malformed input cannot leave
    the repo half-offboarded; strips use an atomic write (§2.5), and the
    declaration/sidecar are removed last so a failed file mutation never orphans the
    declaration.
    """
    root = Path(root)
    result = OffboardingResult()

    # Validate every prospective managed/static target before the first mutation.
    # The guards are repeated immediately at each read/write/delete boundary below
    # to avoid relying on this preflight as the only check.
    preflight = {
        output: confined_target(root, output, operation="preflight offboard target") for output in managed_outputs
    }
    declaration_output = ".github/aviato.yaml"
    sidecar_output = ".github/aviato.seed.json"
    preflight[declaration_output] = confined_target(
        root, declaration_output, operation="preflight offboard declaration"
    )
    preflight[sidecar_output] = confined_target(root, sidecar_output, operation="preflight offboard sidecar")

    # Classify everything first (no mutation), so a read/parse problem aborts before
    # any file is changed rather than midway through (§2.5 managed-file safety).
    to_strip: list[tuple[str, Path, str]] = []
    to_remove: list[tuple[str, Path]] = []
    for output in managed_outputs:
        target = confined_target(root, output, operation="read offboard target")
        if not target.is_file():
            continue
        try:
            target = confined_target(root, output, operation="read offboard target")
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # N3: an AUTOMATION workflow that exists but can't be marker-verified must NOT be silently
            # skipped — offboarding then removes the declaration and leaves it running unmanaged (it
            # would fail/no-op on every schedule). Fail closed so the operator handles it. A passive
            # non-UTF-8 file is genuinely operator-owned — leave it.
            if _is_consumer_automation(output):
                raise AviatoError(
                    f"automation workflow {output} is not valid UTF-8, so its Aviato marker cannot be "
                    "verified; offboarding would leave it running unmanaged. Remove or fix it, then re-run."
                ) from None
            continue
        if parse_marker_from_text(text) is None:
            if _is_consumer_automation(output):
                raise AviatoError(
                    f"automation workflow {output} carries no Aviato marker; offboarding would remove the "
                    "declaration and leave this workflow running unmanaged. Remove or restore its marker, "
                    "then re-run."
                )
            continue  # passive unmanaged / operator-owned file — leave alone
        # Automation workflows are always removed (§5.13); only passive managed files
        # honor the operator's keep-files choice.
        if keep_files and not _is_consumer_automation(output):
            to_strip.append((output, target, strip_marker_from_text(text)))
        else:
            to_remove.append((output, target))

    for output, _target, stripped in to_strip:
        atomic_write(root, output, stripped, operation="write offboard target")
        result.stripped.append(output)
    for output, _target in to_remove:
        target = confined_target(root, output, operation="delete offboard target")
        target.unlink()
        result.removed.append(output)

    declaration = confined_target(root, declaration_output, operation="inspect offboard declaration")
    if declaration.is_file():
        declaration = confined_target(root, declaration_output, operation="delete offboard declaration")
        declaration.unlink()
        result.declaration_removed = True

    sidecar = confined_target(root, sidecar_output, operation="inspect offboard sidecar")
    if sidecar.is_file():
        sidecar = confined_target(root, sidecar_output, operation="delete offboard sidecar")
        sidecar.unlink()
        result.sidecar_removed = True

    return result
