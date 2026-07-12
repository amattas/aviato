"""Local-gate ↔ CI parity guards (review findings 14/44/45).

validate.sh skips missing tools with a banner; CI must run STRICT so a tool
vanishing from the runner cannot silently green the gate. And every tool the
banner set names must actually be provided in CI — via the [dev] extras or an
explicit ci.yml install step — or strict mode would hard-fail structurally
rather than on real regressions.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

from aviato.paths import REPO_ROOT

_VALIDATE = (REPO_ROOT / "scripts" / "validate.sh").read_text(encoding="utf-8")
_CI_TEXT = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
_PYPROJECT = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


def _validate_step() -> dict:
    ci = yaml.safe_load(_CI_TEXT)
    steps = ci["jobs"]["validate"]["steps"]
    return next(s for s in steps if str(s.get("run", "")).strip().startswith("./scripts/validate.sh"))


def test_ci_runs_validate_strict() -> None:
    step = _validate_step()
    assert step.get("env", {}).get("AVIATO_STRICT_TOOLS") == "1", (
        "ci.yml must run validate.sh with AVIATO_STRICT_TOOLS=1 — otherwise a tool "
        "missing from the runner is silently skipped and CI stays green"
    )


def test_every_banner_tool_is_provided_in_ci() -> None:
    tools = set(re.findall(r"command -v (\w+)", _VALIDATE))
    if "import build" in _VALIDATE:
        tools.add("build")
    assert tools, "validate.sh banner tool set unexpectedly empty"
    for tool in sorted(tools):
        pinned_in_extras = f'"{tool}==' in _PYPROJECT
        installed_in_ci = tool in _CI_TEXT
        assert pinned_in_extras or installed_in_ci, (
            f"validate.sh gates on {tool!r} but neither the [dev] extras pin it nor "
            f"ci.yml installs it — strict CI would fail structurally"
        )


def test_yamllint_runs_repo_relative() -> None:
    # .yamllint.yml ignore globs are relative; an absolute-path invocation would
    # bypass them and lint the placeholder-bearing scaffold bodies (finding 44).
    assert "yamllint -s ." in _VALIDATE


def test_wheel_package_data_is_asserted() -> None:
    # The build block must verify aviato/library/** actually ships in the wheel,
    # not merely that the build exits zero (finding 45).
    assert "aviato/library/policy.yml" in _VALIDATE


def test_wheel_runtime_version_parity_is_asserted() -> None:
    assert "METADATA" in _VALIDATE
    assert "from aviato import __version__" in _VALIDATE
    assert 'find_spec("pip")' in _VALIDATE
    assert 'shutil.which("uv")' in _VALIDATE


def test_build_probe_uses_distribution_metadata_and_ignores_shadow_directory(tmp_path: Path) -> None:
    """A local ``build/`` package cannot make the wheel gate look installed."""
    shadow = tmp_path / "shadow"
    (shadow / "build").mkdir(parents=True)
    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "python3"
    wrapper.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *"importlib.metadata"*"version(\'build\')"*) exit 1 ;;\n'
        "esac\n"
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    zizmor = shutil.which("zizmor")
    assert zizmor is not None
    (wrapper_dir / "zizmor").symlink_to(zizmor)
    env = os.environ.copy()
    env["PATH"] = f"{wrapper_dir}:/usr/bin:/bin"
    env["PYTHONPATH"] = str(shadow)
    env.pop("AVIATO_STRICT_TOOLS", None)

    result = subprocess.run(
        ["bash", "scripts/validate.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "build (wheel packaging + package-data)" in output
    assert "LOCAL GATE INCOMPLETE" in output
    assert "No module named build" not in output


def test_wheel_build_uses_modern_license_metadata_without_setuptools_warning(tmp_path: Path) -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["license"] == "MIT"
    assert pyproject["project"]["license-files"] == ["LICENSE"]

    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(tmp_path / "wheel")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "SetuptoolsDeprecationWarning" not in output
