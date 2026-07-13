#!/usr/bin/env python3
"""Synchronize committed docs requirements from the offline pin manifest."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from aviato.core.marker import content_hash
from aviato.core.pathguard import confined_target
from aviato.paths import REPO_ROOT

_SOURCE = Path("aviato/library/docs-toolchain.yaml")
_OUTPUTS = (
    Path("website/requirements.txt"),
    Path("starter/docs-site/requirements.txt"),
    Path("aviato/library/scaffold/files/docs-requirements.txt.txt"),
)
_INPUT_HASH = "c87eec0cc6164b4a0fb591c6236ef87133960db010cc737ecb6d7c9680304085"


def _requirements(pins: dict[str, str], *, starter: bool) -> str:
    comment = (
        "# Docs toolchain — exact pins; update aviato/library/docs-toolchain.yaml."
        if starter
        else "# Aviato-managed docs toolchain (§13.3). Exact pins only (§11.3); update docs-toolchain.yaml."
    )
    return f"{comment}\nzensical=={pins['zensical']}\nmike @ {pins['mike']}\n"


def _preflight_outputs(root: Path) -> dict[Path, Path]:
    """Confine the complete output set before any generator content I/O."""
    return {
        rel_path: confined_target(root, rel_path.as_posix(), operation="synchronize docs toolchain output")
        for rel_path in _OUTPUTS
    }


def _render_outputs(source: Path) -> dict[Path, str]:
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"zensical", "mike", "pydoc-markdown"}:
        raise ValueError("docs-toolchain.yaml must define exactly zensical, mike, and pydoc-markdown")
    pins = {str(key): str(value) for key, value in raw.items()}
    index_pin = re.compile(r"[0-9]+(?:\.[0-9]+)+")
    vcs_pin = re.compile(r"git\+https://[^\s@]+@[0-9a-f]{40}")
    if (
        index_pin.fullmatch(pins["zensical"]) is None
        or index_pin.fullmatch(pins["pydoc-markdown"]) is None
        or vcs_pin.fullmatch(pins["mike"]) is None
    ):
        raise ValueError("docs-toolchain.yaml contains an invalid exact pin")
    managed_body = _requirements(pins, starter=False)
    marker = (
        f"# aviato:managed profile=aviato-library version=0 hash={content_hash(managed_body)} inputs={_INPUT_HASH}\n"
    )
    return {
        _OUTPUTS[0]: marker + managed_body,
        _OUTPUTS[1]: _requirements(pins, starter=True),
        _OUTPUTS[2]: managed_body,
    }


def render_outputs(root: Path = REPO_ROOT) -> dict[Path, str]:
    _preflight_outputs(root)
    source = confined_target(root, _SOURCE.as_posix(), operation="read docs toolchain pin source")
    return _render_outputs(source)


def sync(root: Path = REPO_ROOT, *, check: bool = False) -> list[Path]:
    targets = _preflight_outputs(root)
    source = confined_target(root, _SOURCE.as_posix(), operation="read docs toolchain pin source")
    rendered = _render_outputs(source)
    drifted: list[Path] = []
    for rel_path, body in rendered.items():
        path = targets[rel_path]
        if not path.is_file() or path.read_bytes() != body.encode("utf-8"):
            drifted.append(rel_path)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body.encode("utf-8"))
                print(f"updated {rel_path}")
    return drifted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    args = parser.parse_args()
    drifted = sync(check=args.check)
    if args.check and drifted:
        for path in drifted:
            print(f"stale docs toolchain output: {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
