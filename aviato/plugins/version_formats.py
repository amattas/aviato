from __future__ import annotations

import json
import re
from pathlib import Path

from aviato.core.errors import AviatoError

# Per-format version-source rewriters (§3.3). Each rewriter names a concrete
# manifest/project-file format (pyproject.toml, package.json, .pbxproj, .plist),
# so this knowledge lives in the plug-in tree, not the agnostic core. The set of
# *locations* a profile bumps is plug-in DATA (``version_source.locations``); this
# module is the matching plug-in LOGIC that knows how to rewrite each format.
_PYPROJECT_VERSION = re.compile(r'(?m)^(?P<prefix>version\s*=\s*)"[^"]*"')
# The package version lives only in [project] (PEP 621) or [tool.poetry]; a stray
# version = "..." in another table (e.g. a bumpver/tool config) must not be touched.
_PYPROJECT_VERSION_TABLES = ("project", "tool.poetry")
_PBXPROJ_MARKETING = re.compile(r"(MARKETING_VERSION = )[^;]+;")
_PBXPROJ_BUILD = re.compile(r"(CURRENT_PROJECT_VERSION = )[^;]+;")
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
        segment, count = _PYPROJECT_VERSION.subn(rf'\g<prefix>"{bare}"', text[start:end], count=1)
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
        data = json.loads(text)
        if not isinstance(data.get("version"), str):
            raise AviatoError(f"no top-level version string found in {filename}")
        span = _top_level_json_string_span(text, "version")
        if span is None:
            raise AviatoError(f"could not locate the top-level version field to rewrite in {filename}")
        return text[: span[0]] + f'"{bare}"' + text[span[1] :]

    if name.endswith(".pbxproj"):
        new = _PBXPROJ_MARKETING.sub(rf"\g<1>{bare};", text)
        if build_number is not None:
            new = _PBXPROJ_BUILD.sub(rf"\g<1>{build_number};", new)
        if new == text:
            raise AviatoError(f"no MARKETING_VERSION found in {filename}")
        return new

    if name.endswith(".plist"):
        new = _PLIST_SHORT.sub(rf"\g<1>{bare}\g<2>", text)
        if build_number is not None:
            new = _PLIST_BUILD.sub(rf"\g<1>{build_number}\g<2>", new)
        if new == text:
            raise AviatoError(f"no CFBundleShortVersionString found in {filename}")
        return new

    return text


def bump_files(root: Path, locations: list[str], new_version: str, build_number: str | None = None) -> list[str]:
    """Bump the version in each existing version-source location under ``root``.

    Returns the list of files actually rewritten.
    """
    changed: list[str] = []
    for location in locations:
        path = Path(root) / location
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        bumped = bump_text(location, text, new_version, build_number)
        if bumped != text:
            path.write_text(bumped, encoding="utf-8")
            changed.append(location)
    return changed
