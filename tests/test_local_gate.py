"""Local-gate ↔ CI parity guards (review findings 14/44/45).

validate.sh skips missing tools with a banner; CI must run STRICT so a tool
vanishing from the runner cannot silently green the gate. And every tool the
banner set names must actually be provided in CI — via the [dev] extras or an
explicit ci.yml install step — or strict mode would hard-fail structurally
rather than on real regressions.
"""

from __future__ import annotations

import re

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
