#!/usr/bin/env python3
"""Regenerate the documented copyable caller templates from the scaffold bundles.

The ``templates/profile-*.yml`` and ``templates/consumer-automation.yml`` files are
human-readable EXAMPLES of what ``aviato sync``/``onboard`` materializes. They are
rendered from the authoritative scaffold bundles (never hand-maintained), so this
script is the only sanctioned way to update them. ``aviato validate`` fails if they
drift from the rendered output (see validation._check_template_scaffold_parity).

Usage: python3 scripts/regen-templates.py
"""

from __future__ import annotations

from aviato.core.onboarding import resolved_artifacts
from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT, REPO_ROOT
from aviato.validation import _PROFILE_TEMPLATE_FILES, _TEMPLATE_EXAMPLE_VARS


def _body(registry: Registry, profile: str, output: str) -> str:
    artifacts = resolved_artifacts(registry, profile, _TEMPLATE_EXAMPLE_VARS[profile], pin="0.1.0", docs=False)
    return next(a.body for a in artifacts if a.output == output)


def main() -> int:
    registry = Registry(MODULE_SOURCE_ROOT)
    for profile, rel_path in _PROFILE_TEMPLATE_FILES.items():
        (REPO_ROOT / rel_path).write_text(_body(registry, profile, ".github/workflows/aviato-ci.yml"), encoding="utf-8")
        print(f"regenerated {rel_path}")
    (REPO_ROOT / "templates" / "consumer-automation.yml").write_text(
        _body(registry, "python-library", ".github/workflows/aviato-drift.yml"), encoding="utf-8"
    )
    print("regenerated templates/consumer-automation.yml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
