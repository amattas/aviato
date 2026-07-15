#!/usr/bin/env python3
"""Regenerate the exact privileged/OIDC execution contract from reviewed workflows."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from aviato.core.onboarding import resolved_artifacts  # noqa: E402
from aviato.core.registry import Registry  # noqa: E402
from aviato.paths import MODULE_SOURCE_ROOT  # noqa: E402
from aviato.plugins.release_mutations import _documents, _privileged_jobs  # noqa: E402
from aviato.validation import _TEMPLATE_EXAMPLE_VARS, TEMPLATE_EXAMPLE_PIN  # noqa: E402

OUTPUT = REPO_ROOT / "aviato/library/privileged-execution-manifest.json"


def rendered_python() -> dict[str, object]:
    artifacts = resolved_artifacts(
        Registry(MODULE_SOURCE_ROOT),
        "python-library",
        _TEMPLATE_EXAMPLE_VARS["python-library"],
        pin=TEMPLATE_EXAMPLE_PIN,
        docs=False,
    )
    body = next(item.body for item in artifacts if item.output == ".github/workflows/aviato-ci.yml")
    document = yaml.safe_load(body)
    if not isinstance(document, dict):
        raise SystemExit("rendered Python caller is not a workflow mapping")
    return document


def generated_body() -> str:
    contracts = _privileged_jobs(_documents(REPO_ROOT / ".github/workflows", rendered_python()))
    payload = [asdict(contracts[key]) for key in sorted(contracts)]
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    body = generated_body()
    if args.check:
        return 0 if OUTPUT.is_file() and OUTPUT.read_text(encoding="utf-8") == body else 1
    OUTPUT.write_text(body, encoding="utf-8")
    print(f"regenerated {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
