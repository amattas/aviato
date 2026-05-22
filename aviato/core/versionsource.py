from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import AviatoError

_PYPROJECT_VERSION = re.compile(r'(?m)^(?P<prefix>version\s*=\s*)"[^"]*"')
_PBXPROJ_MARKETING = re.compile(r"(MARKETING_VERSION = )[^;]+;")
_PBXPROJ_BUILD = re.compile(r"(CURRENT_PROJECT_VERSION = )[^;]+;")
_PLIST_SHORT = re.compile(r"(<key>CFBundleShortVersionString</key>\s*<string>)[^<]*(</string>)")
_PLIST_BUILD = re.compile(r"(<key>CFBundleVersion</key>\s*<string>)[^<]*(</string>)")


def _bare(version: str) -> str:
    """Manifest version strings are bare SemVer (no leading ``v``)."""
    return version[1:] if version.startswith("v") else version


def bump_text(filename: str, text: str, new_version: str, build_number: str | None = None) -> str:
    """Rewrite the version string(s) in a version-source file's text (§3.3).

    Manifests record bare SemVer (the leading ``v`` is stripped). App-bundle project
    files (``.pbxproj``/``.plist``) get the marketing version plus a strictly-increasing
    build number (§12.3/§13.4). An unsupported filename is returned unchanged.
    """
    name = Path(filename).name
    bare = _bare(new_version)

    if name == "pyproject.toml":
        new, count = _PYPROJECT_VERSION.subn(rf'\g<prefix>"{bare}"', text)
        if count == 0:
            raise AviatoError(f"no version field found in {filename}")
        return new

    if name == "package.json":
        data = json.loads(text)
        data["version"] = bare
        return json.dumps(data, indent=2) + "\n"

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
