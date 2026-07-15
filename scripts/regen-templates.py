#!/usr/bin/env python3
"""Regenerate the documented copyable caller templates from the scaffold bundles.

The ``templates/profile-*.yml`` and ``templates/consumer-automation.yml`` files are
human-readable EXAMPLES of what ``aviato sync``/``onboard`` materializes. They are
compiled from the authoritative pipeline graph, envelopes, and one-job fragments, so this
script is the only sanctioned way to update them. ``aviato validate`` fails if they
drift from the rendered output (see validation._check_template_scaffold_parity).

Usage: python3 scripts/regen-templates.py [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Direct script execution otherwise lets an editable install from another
# worktree win module resolution.  Generator input must always come from the
# checkout whose outputs are being regenerated.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aviato.core.declaration import load_declaration
from aviato.core.onboarding import materialize_items, resolved_artifacts
from aviato.core.pathguard import confined_target
from aviato.core.registry import Registry
from aviato.core.scaffold import render_managed
from aviato.paths import REPO_ROOT
from aviato.validation import _PROFILE_TEMPLATE_FILES, _TEMPLATE_EXAMPLE_VARS, TEMPLATE_EXAMPLE_PIN


def _body(registry: Registry, profile: str, output: str) -> str:
    artifacts = resolved_artifacts(
        registry, profile, _TEMPLATE_EXAMPLE_VARS[profile], pin=TEMPLATE_EXAMPLE_PIN, docs=False
    )
    return next(a.body for a in artifacts if a.output == output)


_OUTPUTS = (
    Path(".github/workflows/aviato-ci.yml"),
    Path(".github/workflows/aviato-drift.yml"),
    Path(".github/workflows/aviato-protection-checkpoint.yml"),
    *(Path(path) for path in _PROFILE_TEMPLATE_FILES.values()),
    Path("templates/consumer-automation.yml"),
    Path("templates/consumer-protection-checkpoint.yml"),
)


def _preflight_outputs(root: Path) -> dict[Path, Path]:
    """Confine the complete output set before rendering reads any source body."""
    return {
        rel_path: confined_target(root, rel_path.as_posix(), operation="regenerate documented template")
        for rel_path in _OUTPUTS
    }


def _render_templates(root: Path) -> dict[Path, str]:
    source_root = root / "aviato/library"
    if not source_root.is_dir():
        raise ValueError(f"missing Library module source: {source_root}")
    registry = Registry(source_root)
    rendered: dict[Path, str] = {}
    for profile, rel_path in _PROFILE_TEMPLATE_FILES.items():
        rendered[Path(rel_path)] = _body(registry, profile, ".github/workflows/aviato-ci.yml")
    rendered[Path("templates/consumer-automation.yml")] = _body(
        registry, "python-library", ".github/workflows/aviato-drift.yml"
    )
    rendered[Path("templates/consumer-protection-checkpoint.yml")] = _body(
        registry, "python-library", ".github/workflows/aviato-protection-checkpoint.yml"
    )
    declaration = load_declaration(root / ".github/aviato.yaml")
    if not declaration.bootstrap:
        raise ValueError(".github/aviato.yaml must declare bootstrap: true")
    bootstrap = materialize_items(
        registry,
        declaration.profile,
        declaration.variables,
        pin=declaration.version,
        docs=declaration.docs,
        bootstrap=True,
        overrides=declaration.overrides,
    )
    bootstrap_by_output = {
        item.output: render_managed(item, profile=declaration.profile, version=declaration.version)
        for item in bootstrap
        if not item.seed_once
    }
    for output in (
        ".github/workflows/aviato-ci.yml",
        ".github/workflows/aviato-drift.yml",
        ".github/workflows/aviato-protection-checkpoint.yml",
    ):
        rendered[Path(output)] = bootstrap_by_output[output]
    return rendered


def render_templates(root: Path = REPO_ROOT) -> dict[Path, str]:
    _preflight_outputs(root)
    return _render_templates(root)


def regenerate(root: Path = REPO_ROOT, *, check: bool = False) -> list[Path]:
    targets = _preflight_outputs(root)
    rendered = _render_templates(root)
    drifted: list[Path] = []
    for rel_path, body in rendered.items():
        path = targets[rel_path]
        if not path.is_file() or path.read_bytes() != body.encode("utf-8"):
            drifted.append(rel_path)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body.encode("utf-8"))
                print(f"regenerated {rel_path}")
    return drifted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    args = parser.parse_args()
    drifted = regenerate(check=args.check)
    if args.check and drifted:
        for path in drifted:
            print(f"stale generated template: {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
