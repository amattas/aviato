#!/usr/bin/env python3
"""Regenerate the exact privileged/OIDC execution contract from reviewed workflows."""

from __future__ import annotations

import argparse
import hashlib
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
from aviato.plugins.release_mutations import (  # noqa: E402
    _documents,
    _privileged_jobs,
    privileged_manifest_sha256,
)
from aviato.validation import _TEMPLATE_EXAMPLE_VARS, TEMPLATE_EXAMPLE_PIN  # noqa: E402

OUTPUT = REPO_ROOT / "aviato/library/privileged-execution-manifest.json"
ATTESTATION = REPO_ROOT / "aviato/library/privileged-review-attestation.json"
POLICY = REPO_ROOT / "aviato/library/privileged-review-policy.json"
CODEOWNERS = REPO_ROOT / ".github/CODEOWNERS"


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


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_review_record(path: Path, body: str) -> None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"--review-record must name a readable JSON record: {exc}") from exc
    if not isinstance(loaded, dict) or loaded.get("schema_version") != 1:
        raise SystemExit("--review-record must use privileged review schema_version 1")
    if loaded.get("status") not in {"pending", "approved"}:
        raise SystemExit("--review-record status must be pending or approved")
    candidate = json.loads(body)
    expected = {
        "candidate_manifest_sha256": privileged_manifest_sha256(tuple(candidate)),
        "policy_sha256": _file_sha256(POLICY),
        "codeowners_sha256": _file_sha256(CODEOWNERS),
    }
    mismatches = [key for key, value in expected.items() if loaded.get(key) != value]
    if mismatches:
        raise SystemExit(
            "--review-record does not acknowledge the current protected candidate: " + ", ".join(mismatches)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--review-record",
        required=True,
        type=Path,
        help="Protected pending-or-approved record acknowledging the exact candidate and review policy.",
    )
    args = parser.parse_args()
    body = generated_body()
    review_record = args.review_record if args.review_record.is_absolute() else REPO_ROOT / args.review_record
    validate_review_record(review_record, body)
    record_body = review_record.read_text(encoding="utf-8")
    if args.check:
        return (
            0
            if OUTPUT.is_file()
            and OUTPUT.read_text(encoding="utf-8") == body
            and ATTESTATION.is_file()
            and ATTESTATION.read_text(encoding="utf-8") == record_body
            else 1
        )
    OUTPUT.write_text(body, encoding="utf-8")
    ATTESTATION.write_text(record_body, encoding="utf-8")
    print(f"regenerated {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
