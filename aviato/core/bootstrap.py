from __future__ import annotations

from pathlib import Path


def is_library(root: Path) -> bool:
    """The §5.10 structural predicate: is ``root`` the Library itself?

    True iff ``root`` contains all of the core engine's source package, the
    module-source tree (``aviato/library`` with its ``bundles/`` and ``scaffold/``
    definition trees), and the project manifest. Detection is by structure, never
    by repository name, so forks/renames are unaffected.
    """
    root = Path(root)
    return all(
        [
            (root / "aviato" / "core" / "__init__.py").is_file(),
            (root / "aviato" / "library" / "bundles").is_dir(),
            (root / "aviato" / "library" / "scaffold").is_dir(),
            (root / "pyproject.toml").is_file(),
        ]
    )
