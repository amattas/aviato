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


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".aviato-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
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
    _atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _render_managed(item: ScaffoldItem, *, profile: str, version: str) -> str:
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
            _atomic_write(target, item.body)
            sidecar[output] = content_hash(item.body)
            sidecar_changed = True
            result.seeded.append(output)
            continue

        rendered = _render_managed(item, profile=profile, version=version)
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing == rendered:
                result.unchanged.append(output)
                continue
            if not force:
                marker = parse_marker_from_text(existing)
                if marker is None:
                    # Unmanaged or malformed-marker file — protect the operator's file.
                    result.skipped_unmanaged.append(output)
                    continue
                if content_hash(strip_marker_from_text(existing)) != marker.hash:
                    # Valid marker but the body diverges from what Aviato last wrote:
                    # the operator hand-edited a managed file → never clobber (§2.5/§5.4).
                    result.skipped_modified.append(output)
                    continue
        _atomic_write(target, rendered)
        result.written.append(output)

    if sidecar_changed:
        _write_sidecar(root, sidecar)

    return result
