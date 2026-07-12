from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .marker import content_hash, parse_marker_from_text, render_marker, strip_marker_from_text
from .pathguard import confined_target
from .version import is_known_version_pin

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
    # Marker present and well-formed, but not a trustworthy managed artifact under THIS
    # declaration: stamped for a different profile, or recording an unknown version. Mirrors
    # diagnosis dirty-drift — never silently regenerated (§5.3/§5.4 one posture).
    skipped_foreign: list[str] = field(default_factory=list)
    seeded: list[str] = field(default_factory=list)


def atomic_write(root: Path, relative: str, text: str | None = None, *, operation: str = "write file") -> None:
    # Keep the original path/text form for non-consumer callers while consumer
    # operations use the root/relative/text form and are re-guarded at replace.
    if text is not None:
        confined = True
        path = confined_target(root, relative, operation=operation)
        rendered = text
    else:
        confined = False
        path = Path(root)
        rendered = relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if confined:
        path = confined_target(root, relative, operation=operation)
    # finding 22: mkstemp creates the temp file 0600 and os.replace carries that mode to
    # the destination — silently DEMOTING an existing file's permissions (group-read,
    # +x) and creating new files stricter than the umask. Preserve an existing file's
    # mode; otherwise honor the process umask like a normal create would.
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".aviato-", suffix=".tmp")
    try:
        # newline="" disables platform newline translation so the bytes on disk are exactly
        # the rendered string — byte-identical output across platforms (§5.3 determinism).
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(rendered)
        os.chmod(tmp_name, mode)
        if confined:
            path = confined_target(root, relative, operation=operation)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_sidecar(root: Path) -> dict[str, str]:
    path = confined_target(root, SIDECAR_PATH, operation="read sidecar")
    if not path.is_file():
        return {}
    # The sidecar is a report-only advisory record (§6.3); a corrupt/truncated/non-UTF-8 one
    # (manual edit, half-written, merge-conflict markers) must degrade to "no recorded hashes",
    # never crash diagnosis/scaffold — and thus never abort a whole fleet scan (the per-repo
    # guard in scan_fleet catches only AviatoError, so a raw JSONDecodeError would escape).
    try:
        path = confined_target(root, SIDECAR_PATH, operation="read sidecar")
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_sidecar(root: Path, data: dict[str, str]) -> None:
    # review #31: each sidecar write is atomic (temp + os.replace via atomic_write), but the
    # read-modify-write within scaffold() is not guarded against a SECOND concurrent scaffold of
    # the SAME local tree (last-writer-wins on the merged dict). The CLI runs one command per
    # process against an operator's local checkout, so concurrent scaffolds of one tree are not an
    # expected workflow; the sidecar is report-only, so the worst case is a stale/incomplete record
    # (no file is ever half-written), recovered on the next single-writer sync.
    atomic_write(
        root,
        SIDECAR_PATH,
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        operation="write sidecar",
    )


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

    # Reject a hostile output before advisory sidecar access can obscure which
    # managed artifact made the requested scaffold unsafe.
    for output in overlay:
        confined_target(root, output, operation="write scaffold output")

    sidecar = read_sidecar(root)
    sidecar_changed = False

    for output, item in overlay.items():
        target = confined_target(root, output, operation="read scaffold output")

        if item.seed_once:
            if target.exists():
                # §6.3 seed-once: never overwrite an existing operator-owned file. But if the
                # sidecar has NO recorded hash for it (the report-only integrity record was
                # deleted/lost, or the file pre-existed adoption), re-establish the baseline from
                # the file's CURRENT content so a deleted sidecar self-heals on the next sync and
                # FUTURE tamper is again visible (§5.14 "absence reads as broken, never clean").
                # This cannot retroactively detect tampering that happened before the heal — the
                # sidecar is an advisory record, not a security boundary; once deleted, prior
                # content is unknowable.
                if output not in sidecar:
                    try:
                        target = confined_target(root, output, operation="read scaffold output")
                        sidecar[output] = content_hash(target.read_text(encoding="utf-8"))
                        sidecar_changed = True
                    except (UnicodeDecodeError, OSError):
                        pass  # binary seed-once file (§6.3), or a directory/unreadable path (N4) — no text hash
                continue
            atomic_write(root, output, item.body, operation="write scaffold output")
            sidecar[output] = content_hash(item.body)
            sidecar_changed = True
            result.seeded.append(output)
            continue

        rendered = render_managed(item, profile=profile, version=version)
        expected_hash = content_hash(item.body)
        if target.exists():
            try:
                target = confined_target(root, output, operation="read scaffold output")
                existing = target.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                # A non-UTF-8 file (or a DIRECTORY / otherwise-unreadable path at the managed output,
                # N4: IsADirectoryError &c. are OSError, not UnicodeDecodeError) cannot carry a valid
                # Aviato marker, so it is operator-owned: never silently regenerate over it (mirrors
                # diagnosis dirty-drift), and never crash a fleet sync. Treated as no-marker unmanaged.
                if not force:
                    result.skipped_unmanaged.append(output)
                    continue
                existing = ""
            marker = parse_marker_from_text(existing)
            if marker is None:
                if not force:
                    # Unmanaged or malformed-marker file — protect the operator's file.
                    result.skipped_unmanaged.append(output)
                    continue
            else:
                if not force and marker.profile != profile:
                    # Marker stamped for a DIFFERENT profile (one profile per repo, §3): not a
                    # trustworthy managed artifact under this declaration. Mirror diagnosis
                    # dirty-drift — never silently regenerate; require human review or --force
                    # (§5.3/§5.4 one posture). Checked before the body compare so a foreign-profile
                    # marker is never reported "unchanged" either.
                    result.skipped_foreign.append(output)
                    continue
                if not force and not is_known_version_pin(marker.version):
                    # Recorded version unknown/unparseable → version compatibility cannot be
                    # established, so the file is never silently regenerated over (mirrors
                    # diagnosis dirty-drift, §5.4). Defense in depth behind the CLI §2.6 gate.
                    result.skipped_foreign.append(output)
                    continue
                body_hash = content_hash(strip_marker_from_text(existing))
                # Body correct, marker hash current, AND marker version current → no-op. The drift
                # hash excludes the version (§5.5), so a scheduled drift run never churns on a
                # version move — but a §5.12 re-pin DELIBERATELY moves the pin, so when only the
                # version differs this is False and we fall through to RESTAMP the marker (the
                # rendered content carries the new version), so `repin` never leaves a stale
                # `version=` on non-pin-bearing files. Not skipped_modified: the body matches
                # expected, so the `body_hash != expected_hash` guard below is False.
                if (
                    body_hash == expected_hash
                    and marker.hash == expected_hash
                    and marker.profile == profile
                    and marker.version == version
                ):
                    result.unchanged.append(output)
                    continue
                # Body matches neither expected nor what Aviato last wrote → the operator
                # hand-edited a managed file → never clobber (§2.5/§5.4); matches
                # diagnosis "dirty-drift".
                if not force and body_hash != expected_hash and body_hash != marker.hash:
                    result.skipped_modified.append(output)
                    continue
                # else: template moved or marker stale → regenerate (diagnosis "mergeable").
        atomic_write(root, output, rendered, operation="write scaffold output")
        result.written.append(output)

    if sidecar_changed:
        _write_sidecar(root, sidecar)

    return result
