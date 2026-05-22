from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .marker import content_hash, parse_marker_from_text, render_marker, strip_marker_from_text

SIDECAR_PATH = ".github/aviato.seed.json"


@dataclass(frozen=True)
class ScaffoldItem:
    """One unit of work for the scaffolder."""

    output: str
    body: str
    comment: str
    seed_once: bool = False


@dataclass
class ScaffoldResult:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped_unmanaged: list[str] = field(default_factory=list)
    skipped_modified: list[str] = field(default_factory=list)
    seeded: list[str] = field(default_factory=list)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".aviato-", suffix=".tmp")
    try:
        # newline="" disables platform newline translation so the bytes on disk are exactly
        # the rendered string — byte-identical output across platforms (§5.3 determinism).
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_sidecar(root: Path) -> dict[str, str]:
    path = Path(root) / SIDECAR_PATH
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _write_sidecar(root: Path, data: dict[str, str]) -> None:
    path = Path(root) / SIDECAR_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def render_managed(item: ScaffoldItem, *, profile: str, version: str) -> str:
    """Render a managed file's full content: the §6.2 marker line followed by the body.

    This is the exact content :func:`scaffold` writes, so a file-drift proposal
    that uses it produces a merge that diagnosis classifies clean (not dirty for a
    missing marker).
    """
    marker = render_marker(profile=profile, version=version, body=item.body, comment=item.comment)
    return f"{marker}\n{item.body}"


def scaffold(
    root: Path,
    items: list[ScaffoldItem],
    *,
    profile: str,
    version: str,
    force: bool = False,
) -> ScaffoldResult:
    """Materialize managed and seed-once artifacts (§5.3, §6.3).

    Managed files are rendered, stamped with the marker, and written atomically;
    an existing unmanaged or malformed-marker file is skipped and reported unless
    ``force`` is set. Seed-once files are written only when absent, recorded in a
    report-only sidecar, and never overwritten.
    """
    root = Path(root)
    result = ScaffoldResult()

    # Overlay: later item wins for the same output path (§5.3).
    overlay: dict[str, ScaffoldItem] = {}
    for item in items:
        overlay[item.output] = item

    sidecar = read_sidecar(root)
    sidecar_changed = False

    for output, item in overlay.items():
        target = root / output

        if item.seed_once:
            if target.exists():
                continue
            atomic_write(target, item.body)
            sidecar[output] = content_hash(item.body)
            sidecar_changed = True
            result.seeded.append(output)
            continue

        rendered = render_managed(item, profile=profile, version=version)
        expected_hash = content_hash(item.body)
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            marker = parse_marker_from_text(existing)
            if marker is None:
                if not force:
                    # Unmanaged or malformed-marker file — protect the operator's file.
                    result.skipped_unmanaged.append(output)
                    continue
            else:
                body_hash = content_hash(strip_marker_from_text(existing))
                # Body correct and marker hash current → no-op (marker version excluded,
                # so a version-only move is not churn; matches diagnosis "clean", §5.5).
                if body_hash == expected_hash and marker.hash == expected_hash:
                    result.unchanged.append(output)
                    continue
                # Body matches neither expected nor what Aviato last wrote → the operator
                # hand-edited a managed file → never clobber (§2.5/§5.4); matches
                # diagnosis "dirty-drift".
                if not force and body_hash != expected_hash and body_hash != marker.hash:
                    result.skipped_modified.append(output)
                    continue
                # else: template moved or marker stale → regenerate (diagnosis "mergeable").
        atomic_write(target, rendered)
        result.written.append(output)

    if sidecar_changed:
        _write_sidecar(root, sidecar)

    return result
