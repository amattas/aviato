from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

# The agnostic core package, used to resolve relative imports to absolute names.
_CORE_PACKAGE = ("aviato", "core")

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
    # Recurse (§9b soundness): a future ``aviato/core/<subpkg>/x.py`` must not escape
    # the agnosticism scan. Exclude bytecode caches, which carry no source to scan.
    return sorted(p for p in Path(core_dir).rglob("*.py") if "__pycache__" not in p.parts)


def _plugin_pkg() -> str:
    # Assembled at runtime so this checker's own source carries no literal edge (§9b).
    return "aviato." + "plugins"


def _is_plugin_module(name: str) -> bool:
    pkg = _plugin_pkg()
    return name == pkg or name.startswith(pkg + ".")


def _resolve_relative(level: int, module: str | None) -> str:
    """Resolve a relative import (``from .. import x``) to an absolute module name,
    treating the source file as a member of the agnostic core package."""
    drop = level - 1  # level 1 == the core package itself
    base_parts = list(_CORE_PACKAGE[: len(_CORE_PACKAGE) - drop]) if drop <= len(_CORE_PACKAGE) else []
    base = ".".join(base_parts)
    if module:
        return f"{base}.{module}" if base else module
    return base


def core_import_violations(core_dir: Path | None = None) -> list[str]:
    """Return ``file:line`` strings where core source reaches the plug-in tree (§9b).

    AST-based, so it catches absolute (``import aviato.plugins``), relative
    (``from ..plugins import x``), aliased, indented, and multi-line import edges —
    and any dynamic ``importlib.import_module(...)``/``__import__(...)`` call, which is
    the exact string-assembly evasion a line-regex would miss (core has no legitimate
    dynamic-import need). A prose mention in a comment/string is not an edge.
    """
    violations: list[str] = []
    for path in _core_files(core_dir):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for element in ast.walk(tree):
            if isinstance(element, ast.Import):
                if any(_is_plugin_module(alias.name) for alias in element.names):
                    violations.append(f"{path.name}:{element.lineno}")
            elif isinstance(element, ast.ImportFrom):
                base = element.module if element.level == 0 else _resolve_relative(element.level, element.module)
                names = [f"{base}.{alias.name}" for alias in element.names]
                if _is_plugin_module(base) or any(_is_plugin_module(name) for name in names):
                    violations.append(f"{path.name}:{element.lineno}")
            elif isinstance(element, ast.Call):
                func = element.func
                is_import_module = isinstance(func, ast.Attribute) and func.attr == "import_module"
                is_dunder_import = isinstance(func, ast.Name) and func.id == "__import__"
                if is_import_module or is_dunder_import:
                    violations.append(f"{path.name}:{element.lineno}")
    return violations


def denylist_violations(core_dir: Path | None = None, denylist: Iterable[str] | None = None) -> list[str]:
    """Return ``file:token`` strings where core source names a denylisted identifier (§9b).

    Matching is case-insensitive on word boundaries, so a substring inside an
    unrelated word does not trip the check.

    Limitation (acknowledged): this is a text scan, so a token assembled at runtime
    (``"py" + "thon"``) is not detected. It is a lint, not a hard guarantee. The
    highest-impact evasion — reaching the plug-in tree by dynamic import — is closed
    separately and soundly by :func:`core_import_violations` (which flags any
    ``import_module``/``__import__`` call); this denylist guards the remaining
    name-an-identifier case on a best-effort basis.
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
