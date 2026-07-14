from __future__ import annotations

from pathlib import Path


def structural_anchors(root: Path) -> tuple[Path, ...]:
    """Return every anchor whose real, non-symlink presence grants bootstrap authority."""

    root = Path(root)
    return (
        root / "aviato" / "core" / "__init__.py",
        root / "aviato" / "library" / "bundles",
        root / "aviato" / "library" / "scaffold",
        root / "aviato" / "library" / "policy.yml",
    )


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

    This predicate establishes structure only; it never grants a bootstrap-only
    compatibility or proposal skip by itself. Callers must also require the operated
    declaration's explicit ``bootstrap: true`` through :func:`bootstrap_authorized`.
    Detection is by structure, never by repository name, so forks/renames are unaffected.
    """
    root = Path(root)
    core, bundles, scaffold, policy = structural_anchors(root)
    return core.is_file() and bundles.is_dir() and scaffold.is_dir() and policy.is_file()


def bootstrap_authorized(root: Path, *, declared: bool) -> bool:
    """Return true only when structure and explicit declaration consent both hold."""

    return declared and is_library(root)
