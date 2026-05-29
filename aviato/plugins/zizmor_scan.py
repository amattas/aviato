"""Run the pinned zizmor (§11.3) and surface only the GATED audits as violations.

Lives in plugins (NOT core): it names a concrete tool, so it would trip the §9b denylist if
placed in aviato/core. The bundled config (aviato/library/zizmor.yml) carries the pin policy.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..command import run
from ..paths import POLICY_DATA_ROOT

ZIZMOR_CONFIG = POLICY_DATA_ROOT / "zizmor.yml"

# Audits aviato gates on today. zizmor runs all audits; we surface only these. Forward-compatible:
# adopting another audit is a one-line addition here (plus a doc note), not a new detector.
_GATED_AUDITS = frozenset({"unpinned-uses", "unpinned-images"})


class ZizmorUnavailable(RuntimeError):
    """zizmor is not installed or failed to run — fail closed (never report 'clean')."""


def _zizmor_available() -> bool:
    return shutil.which("zizmor") is not None


def _finding_location(finding: dict) -> str:
    """Best-effort 'file' string from a zizmor JSON finding (schema-tolerant).

    Real shape verified against zizmor 1.25.2:
    locations[i]["symbolic"]["key"]["Local"]["given_path"].
    """
    for loc in finding.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        key = (loc.get("symbolic") or {}).get("key")
        local = key.get("Local") if isinstance(key, dict) else None
        if isinstance(local, dict):
            name = local.get("given_path") or local.get("prefix")
            if name:
                return str(name)
    return finding.get("ident", "?")


def zizmor_uses_image_violations(workflow_dir: Path) -> list[str]:
    """Return gated zizmor findings for ``workflow_dir`` as ``ident: file`` strings.

    Empty if the directory is absent. Raises :class:`ZizmorUnavailable` if zizmor is missing or
    errors (§5.14: an unrunnable gate reads as broken, never silently clean).
    """
    workflow_dir = Path(workflow_dir)
    if not workflow_dir.is_dir():
        return []
    if not _zizmor_available():
        raise ZizmorUnavailable("zizmor is not on PATH; it is a pinned dependency of aviato (pip install aviato)")
    # --no-exit-codes: findings no longer set exit 11-14, so a non-zero code means a real ERROR
    # (1 audit error / 2 argparse / 3 no inputs). We detect findings from the JSON, not the code.
    result = run(
        [
            "zizmor",
            "--config",
            str(ZIZMOR_CONFIG),
            "--format",
            "json",
            "--no-exit-codes",
            str(workflow_dir),
        ],
        check=False,
    )
    if result.returncode == 3:  # no inputs collected (no workflows) — clean
        return []
    if result.returncode != 0:
        raise ZizmorUnavailable(f"zizmor failed (exit {result.returncode}): {result.stderr.strip()}")
    if not result.stdout.strip():
        return []
    try:
        findings = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ZizmorUnavailable(f"could not parse zizmor JSON output: {exc}") from exc
    violations = {
        f"{f.get('ident')}: {_finding_location(f)}"
        for f in findings
        if isinstance(f, dict) and f.get("ident") in _GATED_AUDITS
    }
    return sorted(violations)
