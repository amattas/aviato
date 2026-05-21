from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import AviatoError

_PYPROJECT_VERSION = re.compile(r'(?m)^(?P<prefix>version\s*=\s*)"[^"]*"')


def bump_text(filename: str, text: str, new_version: str) -> str:
    """Rewrite the version string in a version-source file's text (§3.3).

    Supports the day-zero manifest formats; an unsupported filename is returned
    unchanged (the language plug-in declares which locations to bump).
    """
    name = Path(filename).name
    if name == "pyproject.toml":
        new, count = _PYPROJECT_VERSION.subn(rf'\g<prefix>"{new_version}"', text)
        if count == 0:
            raise AviatoError(f"no version field found in {filename}")
        return new
    if name == "package.json":
        data = json.loads(text)
        data["version"] = new_version
        return json.dumps(data, indent=2) + "\n"
    return text


def bump_files(root: Path, locations: list[str], new_version: str) -> list[str]:
    """Bump the version in each existing version-source location under ``root``.

    Returns the list of files actually rewritten.
    """
    changed: list[str] = []
    for location in locations:
        path = Path(root) / location
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        bumped = bump_text(location, text, new_version)
        if bumped != text:
            path.write_text(bumped, encoding="utf-8")
            changed.append(location)
    return changed
