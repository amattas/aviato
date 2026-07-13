"""Aviato policy and repository tooling."""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

__all__ = ["__version__"]

_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(?:alpha|beta)[0-9]+)?$")


def _source_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str):
        raise RuntimeError(f"{pyproject} does not define project.version")
    if _SEMVER_RE.fullmatch(version) is None:
        raise RuntimeError(f"{pyproject} project.version is not valid SemVer: {version!r}")
    return version


def _runtime_version() -> str:
    try:
        return metadata.version("aviato")
    except metadata.PackageNotFoundError:
        return _source_version()


__version__ = _runtime_version()
