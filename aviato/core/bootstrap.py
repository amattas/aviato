from __future__ import annotations

from pathlib import Path


def is_library(root: Path) -> bool:
    """The §5.10 structural predicate: is ``root`` the Library itself?

    True iff ``root`` contains the core engine's source package and the
    module-source tree (``aviato/library`` with its ``bundles/`` and ``scaffold/``
    definition trees). Detection is by structure, never by repository name or a
    language-specific manifest, so forks/renames (and the agnosticism rule) are
    unaffected — an installed-as-dependency consumer lacks this source layout in
    its own root.
    """
    root = Path(root)
    return all(
        [
            (root / "aviato" / "core" / "__init__.py").is_file(),
            (root / "aviato" / "library" / "bundles").is_dir(),
            (root / "aviato" / "library" / "scaffold").is_dir(),
        ]
    )
