from __future__ import annotations

import json
import re
from pathlib import Path

from aviato.core.errors import AviatoError
from aviato.core.pathguard import confined_target
from aviato.core.scaffold import atomic_write

# Per-format version-source rewriters (§3.3). Each rewriter names a concrete
# manifest/project-file format (pyproject.toml, package.json, .pbxproj, .plist),
# so this knowledge lives in the plug-in tree, not the agnostic core. The set of
# *locations* a profile bumps is plug-in DATA (``version_source.locations``); this
# module is the matching plug-in LOGIC that knows how to rewrite each format.
# Match either quote style (TOML/PEP 621 permits single OR double quotes); the closing
# quote is a backreference so the original style is preserved on rewrite.
_PYPROJECT_VERSION = re.compile(r'(?m)^(?P<prefix>version\s*=\s*)(?P<q>["\'])[^"\']*(?P=q)')
# The package version lives only in [project] (PEP 621) or [tool.poetry]; a stray
# version = "..." in another table (e.g. a bumpver/tool config) must not be touched.
_PYPROJECT_VERSION_TABLES = ("project", "tool.poetry")
# Tolerate any spacing around '=' (a hand-edited pbxproj need not use Xcode's canonical
# single spaces); the captured prefix preserves the file's original spacing on rewrite.
_PBXPROJ_MARKETING = re.compile(r"(MARKETING_VERSION\s*=\s*)[^;]+;")
_PBXPROJ_BUILD = re.compile(r"(CURRENT_PROJECT_VERSION\s*=\s*)[^;]+;")
_PLIST_SHORT = re.compile(r"(<key>CFBundleShortVersionString</key>\s*<string>)[^<]*(</string>)")
_PLIST_BUILD = re.compile(r"(<key>CFBundleVersion</key>\s*<string>)[^<]*(</string>)")


def _bare(version: str) -> str:
    """Manifest version strings are bare SemVer (a legacy leading ``v`` is stripped)."""
    return version[1:] if version.startswith("v") else version


def _rewrite_toml_table_version(text: str, tables: tuple[str, ...], bare: str) -> tuple[str, int]:
    """Rewrite the first ``version = "..."`` inside one of ``tables`` (e.g. ``project``).

    Scoped to a single table's span so a ``version`` key in an unrelated table is
    never rewritten. Preserves all surrounding formatting (no reserialization).
    """
    for table in tables:
        header = re.search(r"(?m)^\[" + re.escape(table) + r"\]\s*$", text)
        if header is None:
            continue
        start = header.end()
        following = re.search(r"(?m)^\[", text[start:])
        end = start + following.start() if following else len(text)
        # Function replacement (not a template string) so a version containing a regex
        # backreference sequence (e.g. ``\g<...>``/``\1``) is spliced literally, never
        # re-interpreted by ``re.sub``.
        segment, count = _PYPROJECT_VERSION.subn(
            lambda m: f"{m.group('prefix')}{m.group('q')}{bare}{m.group('q')}", text[start:end], count=1
        )
        if count:
            return text[:start] + segment + text[end:], count
    return text, 0


def _top_level_json_string_span(text: str, key: str) -> tuple[int, int] | None:
    """Return the (start, end) span of the value string literal for a depth-1 object
    ``key``, scanning JSON structurally so a nested key of the same name is skipped.

    Returned span includes both surrounding quotes; ``None`` if no depth-1 string
    value for ``key`` is found.
    """
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            token = text[i + 1 : j]
            after = j + 1
            while after < n and text[after] in " \t\r\n":
                after += 1
            if depth == 1 and token == key and after < n and text[after] == ":":
                value = after + 1
                while value < n and text[value] in " \t\r\n":
                    value += 1
                if value < n and text[value] == '"':
                    w = value + 1
                    while w < n and text[w] != '"':
                        w += 2 if text[w] == "\\" else 1
                    return (value, w + 1)
                return None
            i = j + 1
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        i += 1
    return None


def bump_text(filename: str, text: str, new_version: str, build_number: str | None = None) -> str:
    """Rewrite the version string(s) in a version-source file's text (§3.3).

    Manifests record bare SemVer (any leading ``v`` is stripped). App-bundle project
    files (``.pbxproj``/``.plist``) get the marketing version plus a strictly-increasing
    build number (§12.3/§13.4). An unsupported filename is returned unchanged.
    """
    name = Path(filename).name
    bare = _bare(new_version)

    if name == "VERSION":
        # A plain-text version file: the packaging-free version-source for a container service
        # (§13.2) whose build artifact is its Dockerfile image, not a wheel — so it carries no
        # [project]/package metadata, just the bare SemVer. The whole file IS the version; rewrite
        # it wholesale (idempotent: a re-bump to the same value yields identical text → no change).
        return f"{bare}\n"

    if name == "pyproject.toml":
        new, count = _rewrite_toml_table_version(text, _PYPROJECT_VERSION_TABLES, bare)
        if count == 0:
            raise AviatoError(f"no [project]/[tool.poetry] version field found in {filename}")
        return new

    if name == "package.json":
        # Validate it is JSON and read the current top-level version, then rewrite ONLY
        # that string in place — never reserialize the whole file (that would churn the
        # operator-owned, seed-once manifest's formatting/key order, §3.3/§6.3). The span
        # is found structurally so a nested object's version key is never rewritten.
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            # review #23: surface a malformed manifest as an AviatoError (the caller-consistent
            # contract every other version-source path uses), never a raw JSONDecodeError.
            raise AviatoError(f"{filename} is not valid JSON: {exc}") from exc
        # finding 21: valid JSON need not be an OBJECT — a top-level array/string/number
        # would AttributeError on .get and escape as a raw traceback.
        if not isinstance(data, dict) or not isinstance(data.get("version"), str):
            raise AviatoError(f"no top-level version string found in {filename}")
        span = _top_level_json_string_span(text, "version")
        if span is None:
            raise AviatoError(f"could not locate the top-level version field to rewrite in {filename}")
        return text[: span[0]] + f'"{bare}"' + text[span[1] :]

    if name.endswith(".pbxproj"):
        # Match COUNT (not text-equality) decides "found": an idempotent re-bump to the
        # value the file already holds is a successful no-op, not a "field missing" error.
        # Function replacements splice the version/build literally (no backreference re-parse).
        new, count = _PBXPROJ_MARKETING.subn(lambda m: f"{m.group(1)}{bare};", text)
        if count == 0:
            raise AviatoError(f"no MARKETING_VERSION found in {filename}")
        if build_number is not None:
            # A supplied build number MUST land somewhere — silently dropping it ships an
            # unchanged CFBundleVersion that App Store Connect rejects (§13.4). Fail loud.
            new, build_count = _PBXPROJ_BUILD.subn(lambda m: f"{m.group(1)}{build_number};", new)
            if build_count == 0:
                raise AviatoError(f"no CURRENT_PROJECT_VERSION found in {filename} to write build number")
        return new

    if name.endswith(".plist"):
        new, count = _PLIST_SHORT.subn(lambda m: f"{m.group(1)}{bare}{m.group(2)}", text)
        if count == 0:
            raise AviatoError(f"no CFBundleShortVersionString found in {filename}")
        if build_number is not None:
            new, build_count = _PLIST_BUILD.subn(lambda m: f"{m.group(1)}{build_number}{m.group(2)}", new)
            if build_count == 0:
                raise AviatoError(f"no CFBundleVersion found in {filename} to write build number")
        return new

    return text


def bump_files(root: Path, locations: list[str], new_version: str, build_number: str | None = None) -> list[str]:
    """Bump the version in each existing version-source location under ``root``.

    Returns the list of files actually rewritten.
    """
    # R5-2-PARTIAL: TWO passes. First read + render EVERY present location (raising on any
    # non-UTF-8/unparseable manifest BEFORE touching disk); only then write the changed ones. A
    # single pass that read-and-wrote each location in turn could leave an EARLIER file already
    # rewritten when a LATER location raised — a partial bump (§2.5 "never half-apply"). The
    # per-file write is still atomic (temp + swap), so the only remaining non-atomicity is a crash
    # BETWEEN two writes, which the idempotent re-run resolves.
    # R6-3-DUP: dedupe locations (preserving first occurrence) so a profile that lists the same
    # version-source path twice doesn't double-write or double-report it in `changed`.
    seen: set[str] = set()
    deduped: list[str] = []
    for loc in locations:
        if loc not in seen:
            seen.add(loc)
            deduped.append(loc)
    locations = deduped
    for location in locations:
        confined_target(root, location, operation="preflight version source")
    pending: list[tuple[str, str]] = []
    for location in locations:
        path = confined_target(root, location, operation="probe version source")
        # C12-R3-3 (§2.5 never-half-apply): distinguish ABSENT (skippable — a profile may list optional
        # locations) from PRESENT-BUT-BROKEN. A configured location that exists but is a directory /
        # symlink / non-regular file is a real misconfiguration: skipping it the same as absent lets the
        # bump half-apply (other locations written) and exit success. Fail closed BEFORE any write.
        if not path.exists():
            continue
        path = confined_target(root, location, operation="probe version source")
        if not path.is_file():
            raise AviatoError(f"version-source location exists but is not a regular file, cannot bump: {location}")
        try:
            path = confined_target(root, location, operation="read version source")
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # R3-4-2/R4-2-BUMP: a non-UTF-8 version-source is not a rewritable text manifest. FAIL
            # CLOSED with a clean AviatoError (caught by the CLI) — never a raw UnicodeDecodeError
            # traceback, and never a silent skip that lets the caller report a false "nothing to
            # bump" success when the version was in fact never written (§3.3/§5.9).
            raise AviatoError(f"version-source file is not valid UTF-8, cannot bump: {location}") from exc
        except OSError as exc:
            # An unreadable present file (permissions, etc.) is present-but-broken, not absent.
            raise AviatoError(f"version-source file cannot be read, cannot bump: {location}: {exc}") from exc
        bumped = bump_text(location, text, new_version, build_number)  # may raise AviatoError (bad manifest)
        if bumped != text:
            pending.append((location, bumped))
    changed: list[str] = []
    for location, bumped in pending:
        atomic_write(root, location, bumped, operation="write version source")
        changed.append(location)
    return changed
