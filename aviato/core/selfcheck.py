from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

# Imported lazily-as-data: this module names neither the plug-in package literal
# nor any denylisted identifier in a way that would trip its own scan. The
# denylist is loaded from data (§9b), never hardcoded here.


def load_denylist(path: Path) -> set[str]:
    """Load the §9b denylist tokens from the maintained data file."""
    tokens: set[str] = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        value = line.strip().lower()
        if value and not value.startswith("#"):
            tokens.add(value)
    return tokens


def _core_files(core_dir: Path | None) -> list[Path]:
    if core_dir is None:
        from ..paths import CORE_DIR

        core_dir = CORE_DIR
    return sorted(Path(core_dir).glob("*.py"))


def core_import_violations(core_dir: Path | None = None) -> list[str]:
    """Return ``file:line`` strings where core source imports the plug-in tree (§9b).

    The plug-in package name is assembled at runtime so this checker's own
    source contains no literal import edge.
    """
    plugin_pkg = "aviato." + "plugins"
    import_re = re.compile(rf"^\s*(?:from|import)\s+{re.escape(plugin_pkg)}\b")
    violations: list[str] = []
    for path in _core_files(core_dir):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if import_re.match(line):
                violations.append(f"{path.name}:{lineno}")
    return violations


def denylist_violations(core_dir: Path | None = None, denylist: Iterable[str] | None = None) -> list[str]:
    """Return ``file:token`` strings where core source names a denylisted identifier (§9b).

    Matching is case-insensitive on word boundaries, so a substring inside an
    unrelated word does not trip the check.
    """
    if denylist is None:
        from ..paths import DENYLIST_FILE

        denylist = load_denylist(DENYLIST_FILE)
    patterns = [(token, re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)) for token in denylist]
    violations: list[str] = []
    for path in _core_files(core_dir):
        text = path.read_text(encoding="utf-8")
        for token, pattern in patterns:
            if pattern.search(text):
                violations.append(f"{path.name}:{token}")
    return violations
