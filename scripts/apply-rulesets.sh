#!/usr/bin/env bash
set -euo pipefail

exec python3 -m aviato.cli apply-rulesets "$@"

