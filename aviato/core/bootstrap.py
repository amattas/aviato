from __future__ import annotations

from pathlib import Path


def is_library(root: Path) -> bool:
    """The §5.10 structural predicate: is ``root`` the Library itself?

    True iff ``root`` contains all three §5.10 anchors: the core engine's source
    package, the module-source tree (``aviato/library`` with its ``bundles/`` and
    ``scaffold/`` definition trees), and the Library's single-source-of-truth
    ``policy.yml`` at the repository root. ``policy.yml`` stands in for §5.10's
    "project manifest" anchor *agnostically* — a language-specific build manifest
    cannot be named here because this predicate lives in the agnostic core (§9b);
    ``policy.yml`` is the distinctive Library artifact and is not a language token.

    The third anchor matters: ``is_library()`` true skips the §2.6 version-pin
    gate, so the predicate must not fire on a partial vendored copy of the
    ``aviato/`` package tree that lacks the repo-root ``policy.yml``. Detection is
    by structure, never by repository name, so forks/renames are unaffected — and
    an installed-as-dependency consumer (package in site-packages, no ``policy.yml``
    at its own root) is correctly not the Library.
    """
    root = Path(root)
    return all(
        [
            (root / "aviato" / "core" / "__init__.py").is_file(),
            (root / "aviato" / "library" / "bundles").is_dir(),
            (root / "aviato" / "library" / "scaffold").is_dir(),
            (root / "policy.yml").is_file(),
        ]
    )
