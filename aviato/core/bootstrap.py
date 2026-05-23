from __future__ import annotations

from pathlib import Path


def is_library(root: Path) -> bool:
    """The §5.10 structural predicate: is ``root`` the Library itself?

    True iff ``root`` contains all §5.10 anchors: the core engine's source package,
    the module-source tree (``aviato/library`` with its ``bundles/`` and ``scaffold/``
    definition trees), and the Library's single-source-of-truth ``policy.yml``
    (``aviato/library/policy.yml``). ``policy.yml`` stands in for §5.10's "project
    manifest" anchor *agnostically* — a language-specific build manifest cannot be
    named here because this predicate lives in the agnostic core (§9b); ``policy.yml``
    is the distinctive Library artifact and is not a language token. It lives inside
    ``aviato/library`` (not the repo root) so it ships in the wheel for installed
    ruleset rendering (§5.6/§11.3): a Library checkout has it, while a Consumer repo —
    which never vendors the ``aviato/`` package tree — has no ``aviato/`` at all, so
    the discrimination is unchanged.

    The anchors matter: ``is_library()`` true skips the §2.6 version-pin gate, so the
    predicate must not fire on a Consumer repository (no ``aviato/`` tree). Detection
    is by structure, never by repository name, so forks/renames are unaffected.
    """
    root = Path(root)
    return all(
        [
            (root / "aviato" / "core" / "__init__.py").is_file(),
            (root / "aviato" / "library" / "bundles").is_dir(),
            (root / "aviato" / "library" / "scaffold").is_dir(),
            (root / "aviato" / "library" / "policy.yml").is_file(),
        ]
    )
