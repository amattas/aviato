#!/usr/bin/env bash
set -euo pipefail

# Local gate. ruff/black/pytest/shellcheck/actionlint run when installed. Missing tools are
# SKIPPED (so the gate is usable without them) but reported in a LOUD banner at the
# end — because CI *does* run them, and a silent skip lets workflow-lint failures slip
# through to CI (e.g. shellcheck findings in reusable workflows). Set
# AVIATO_STRICT_TOOLS=1 for CI-parity: a missing tool then fails the gate.
SKIPPED=()

python3 -m compileall aviato >/dev/null
python3 -m aviato.cli validate

if command -v ruff >/dev/null 2>&1; then
  ruff check .
  ruff format --check .
else
  SKIPPED+=("ruff (lint + format)")
fi

if command -v black >/dev/null 2>&1; then
  black --check --line-length 120 --target-version py311 aviato tests scripts
else
  SKIPPED+=("black (formatter compatibility)")
fi

if command -v pytest >/dev/null 2>&1; then
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest
else
  SKIPPED+=("pytest (test suite)")
fi

# Must run from the repo root: .yamllint.yml's ignore globs are relative, and an
# absolute-path invocation bypasses them (the scaffold caller bodies carry {{ }}
# placeholders that are deliberately excluded). Same invocation as
# reusable-common-lint.yml's blocking step.
if command -v yamllint >/dev/null 2>&1; then
  yamllint -s .
else
  SKIPPED+=("yamllint (YAML lint)")
fi

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck scripts/*.sh
else
  SKIPPED+=("shellcheck (script + workflow shell lint)")
fi

if command -v actionlint >/dev/null 2>&1; then
  actionlint
else
  SKIPPED+=("actionlint (.github/workflows lint)")
fi

if [ "${#SKIPPED[@]}" -gt 0 ]; then
  echo
  echo "############################################################"
  echo "## ⚠  LOCAL GATE INCOMPLETE — ${#SKIPPED[@]} tool(s) NOT installed"
  echo "## These run in CI; a green local gate does NOT mean CI is green:"
  for tool in "${SKIPPED[@]}"; do
    echo "##   - ${tool}"
  done
  echo "## Install them (e.g. 'python3 -m pip install -e .[dev]' and 'brew install shellcheck actionlint')"
  echo "## or run with AVIATO_STRICT_TOOLS=1 to fail on missing tools."
  echo "############################################################"
  if [ "${AVIATO_STRICT_TOOLS:-0}" = "1" ]; then
    echo "AVIATO_STRICT_TOOLS=1: failing because tool(s) above are missing." >&2
    exit 1
  fi
fi
