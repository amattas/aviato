#!/usr/bin/env bash
set -euo pipefail

python3 -m compileall aviato >/dev/null
python3 -m aviato.cli validate

if command -v ruff >/dev/null 2>&1; then
  ruff check .
  ruff format --check .
else
  echo "SKIP: ruff is not installed"
fi

if command -v pytest >/dev/null 2>&1; then
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest
else
  echo "SKIP: pytest is not installed"
fi

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck scripts/*.sh
else
  echo "SKIP: shellcheck is not installed"
fi

if command -v actionlint >/dev/null 2>&1; then
  actionlint
else
  echo "SKIP: actionlint is not installed"
fi
