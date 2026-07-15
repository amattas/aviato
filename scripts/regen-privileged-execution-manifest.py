#!/usr/bin/env python3
"""Regenerate the exact privileged/OIDC execution contract from reviewed workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
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
    verify_privileged_review_envelope,
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


def validate_review_record(path: Path, body: str) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"--review-record must name a readable JSON record: {exc}") from exc
    if not isinstance(loaded, dict) or loaded.get("schema_version") != 2:
        raise SystemExit("--review-record must use privileged review schema_version 2 pending declaration")
    if loaded.get("status") != "pending" or loaded.get("lifecycle") != "pending":
        raise SystemExit(
            "--review-record accepts only an honest pending declaration; "
            "approved evidence must be signed and live verified"
        )
    if (
        not isinstance(loaded.get("activation_request_id"), str)
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            str(loaded.get("activation_request_id")),
        )
        is None
        or not isinstance(loaded.get("activation_nonce"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(loaded.get("activation_nonce"))) is None
    ):
        raise SystemExit("--review-record requires one fresh canonical activation request ID and nonce")
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
    return loaded


def _local_protected_inventory(protected_paths: list[str]) -> list[dict[str, str]]:
    normalized: list[str] = []
    for logical in protected_paths:
        if not logical.startswith("/") or ".." in Path(logical).parts:
            raise SystemExit(f"trusted protected path is invalid: {logical}")
        normalized.append(logical)

    def git(*args: str) -> bytes:
        result = subprocess.run(
            ["/usr/bin/git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit("protected inventory requires one readable Git index")
        return result.stdout

    try:
        top = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    except (UnicodeDecodeError, OSError) as exc:
        raise SystemExit("protected inventory requires one readable Git worktree") from exc
    if top != REPO_ROOT.resolve():
        raise SystemExit("protected inventory Git root differs from the source root")

    def covered(repo_path: str) -> bool:
        logical = "/" + repo_path
        return any(logical == item or (item.endswith("/") and logical.startswith(item)) for item in normalized)

    selected: dict[str, tuple[str, str, Path]] = {}
    try:
        records = git("ls-files", "--stage", "-z").split(b"\0")
        for raw in records:
            if not raw:
                continue
            index_metadata, encoded_path = raw.split(b"\t", 1)
            mode, blob_sha, stage = index_metadata.decode("ascii").split(" ")
            repo_path = encoded_path.decode("utf-8")
            if not covered(repo_path):
                continue
            if stage != "0" or mode not in {"100644", "100755"} or re.fullmatch(r"[0-9a-f]{40}", blob_sha) is None:
                raise SystemExit(f"protected path is not one regular stage-zero Git file: /{repo_path}")
            logical = "/" + repo_path
            if logical in selected:
                raise SystemExit(f"protected path is duplicated in the Git index: {logical}")
            selected[logical] = (mode, blob_sha, REPO_ROOT / repo_path)
        untracked = [
            item.decode("utf-8")
            for item in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
            if item
        ]
    except (UnicodeDecodeError, ValueError) as exc:
        raise SystemExit("protected Git index contains an invalid path or entry") from exc
    unexpected = sorted(path for path in untracked if covered(path))
    if unexpected:
        raise SystemExit(f"protected directory contains untracked files: {unexpected!r}")
    for logical in normalized:
        if not any(
            candidate == logical or (logical.endswith("/") and candidate.startswith(logical)) for candidate in selected
        ):
            raise SystemExit(f"trusted protected path is absent from the Git index: {logical}")

    inventory: list[dict[str, str]] = []
    for logical, (index_mode, index_blob_sha, path) in sorted(selected.items()):
        try:
            file_metadata = path.lstat()
        except OSError as exc:
            raise SystemExit(f"protected tracked path is absent or unreadable: {logical}: {exc}") from exc
        if not stat.S_ISREG(file_metadata.st_mode):
            raise SystemExit(f"protected path is not one regular non-symlink file: {logical}")
        working_mode = "100755" if file_metadata.st_mode & stat.S_IXUSR else "100644"
        if working_mode != index_mode:
            raise SystemExit(f"protected working-tree mode differs from the Git index: {logical}")
        body = path.read_bytes()
        git_blob_sha = hashlib.sha1(f"blob {len(body)}\0".encode("ascii") + body).hexdigest()
        if git_blob_sha != index_blob_sha:
            raise SystemExit(f"protected working-tree bytes differ from the Git index: {logical}")
        inventory.append({"path": logical, "mode": index_mode, "sha256": hashlib.sha256(body).hexdigest()})
    return inventory


def validate_approved_envelope(path: Path, body: str) -> tuple[dict[str, object], dict[str, object]]:
    """Allow packaging only after the external signed envelope verifies live."""

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"--approved-envelope must name readable canonical JSON: {exc}") from exc
    if not isinstance(loaded, dict) or loaded.get("schema") != "aviato-privileged-review-envelope/v1":
        raise SystemExit("--approved-envelope requires one canonical signed privileged-review envelope")
    try:
        from time import time

        from aviato.plugins.privileged_review import (
            collect_live_privileged_review_evidence,
            verify_ssh_review_signature,
        )

        trusted_policy, current_policy, live = collect_live_privileged_review_evidence(loaded)
        errors = verify_privileged_review_envelope(
            loaded,
            trusted_base_policy=trusted_policy,
            current_policy=current_policy,
            live_evidence=live,
            now=int(time()),
            verify_signature=verify_ssh_review_signature,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"--approved-envelope live verification failed closed: {exc}") from exc
    candidate = json.loads(body)
    protected = loaded.get("evidence", {}).get("protected_files", [])
    protected_paths = trusted_policy.get("protected_paths")
    if (
        not isinstance(protected, list)
        or not isinstance(protected_paths, list)
        or any(not isinstance(item, str) for item in protected_paths)
    ):
        errors.append("approved evidence/trusted policy protected-file inventory is invalid")
        protected_paths = []
    local_inventory = _local_protected_inventory(protected_paths)
    if protected != local_inventory:
        errors.append("approved evidence does not exactly match every local protected path, mode, and content hash")
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != next(
        (
            item.get("sha256")
            for item in local_inventory
            if item.get("path") == "/aviato/library/privileged-execution-manifest.json"
        ),
        None,
    ):
        errors.append("generated privileged manifest differs from the merged reviewed protected file")
    if loaded.get("evidence", {}).get("pull_request", {}).get("protected_tree_root") is None:
        errors.append("approved evidence omits the reviewed merged protected-tree root")
    if privileged_manifest_sha256(tuple(candidate)) == "":  # pragma: no cover - defensive type boundary
        errors.append("approved evidence candidate manifest identity is invalid")
    if errors:
        raise SystemExit("--approved-envelope is not operationally ready: " + "; ".join(errors))
    return loaded, trusted_policy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    review = parser.add_mutually_exclusive_group(required=True)
    review.add_argument(
        "--review-record",
        type=Path,
        help="Protected schema-v2 pending declaration for static validation/checking.",
    )
    review.add_argument(
        "--approved-envelope",
        type=Path,
        help="Externally signed envelope; accepted only after fresh live verification.",
    )
    parser.add_argument(
        "--package-output-dir",
        type=Path,
        help="Build-only output directory outside the source tree; required with --approved-envelope.",
    )
    args = parser.parse_args()
    body = generated_body()
    selected = args.review_record or args.approved_envelope
    review_record = selected if selected.is_absolute() else REPO_ROOT / selected
    if args.review_record:
        validate_review_record(review_record, body)
    else:
        validate_approved_envelope(review_record, body)
    record_body = review_record.read_text(encoding="utf-8")
    output = OUTPUT
    attestation = ATTESTATION
    if args.approved_envelope:
        if args.package_output_dir is None:
            raise SystemExit("--approved-envelope requires --package-output-dir so packaging cannot dirty source")
        package_root = args.package_output_dir.resolve()
        repo_root = REPO_ROOT.resolve()
        try:
            package_root.relative_to(repo_root)
        except ValueError:
            pass
        else:
            raise SystemExit("--package-output-dir must be outside the post-merge source tree")
        output = package_root / OUTPUT.name
        attestation = package_root / ATTESTATION.name
    if args.check:
        return (
            0
            if output.is_file()
            and output.read_text(encoding="utf-8") == body
            and attestation.is_file()
            and attestation.read_text(encoding="utf-8") == record_body
            else 1
        )
    if args.approved_envelope:
        os.makedirs(output.parent, mode=0o700, exist_ok=True)
    output.write_text(body, encoding="utf-8")
    attestation.write_text(record_body, encoding="utf-8")
    label = str(output) if args.approved_envelope else str(output.relative_to(REPO_ROOT))
    print(f"regenerated {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
