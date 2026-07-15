"""Build Aviato release archives only from one live-verified privileged review."""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .privileged_review import _decode_content, _repository_slug, _rest, verify_signed_envelope

_TRUSTED_REPOSITORY = "amattas/aviato"
_TRUSTED_WORKFLOW = ".github/workflows/aviato-privileged-review.yml"
_TOKEN_ENV = "AVIATO_PRIVILEGED_REVIEW_TOKEN"
_MAX_ARTIFACT_BYTES = 100_000
_ENVELOPE_NAME = "aviato-privileged-review-consumed.json"
_ENVELOPE_DIGEST_NAME = "aviato-privileged-review-consumed.sha256"


@dataclass(frozen=True)
class VerifiedArtifact:
    run_id: int
    artifact_id: int
    artifact_name: str
    artifact_digest: str
    gated_sha: str


def _positive(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be one positive integer")
    return value


def _sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"{label} must be one immutable Git SHA")
    return value


def select_verified_artifact(
    repository: str,
    run_id: int,
    *,
    expected_gated_sha: str,
    token: str,
) -> VerifiedArtifact:
    """Select one exact successful verify run/artifact and derive its gated SHA."""

    repository = _repository_slug(repository)
    if repository != _TRUSTED_REPOSITORY:
        raise ValueError("approved privileged-review builds are self-only")
    run_id = _positive(run_id, label="verify workflow run id")
    expected_gated_sha = _sha(expected_gated_sha, label="caller gated SHA")
    run = _rest(f"/repos/{repository}/actions/runs/{run_id}", token=token)
    run_repository = run.get("repository") if isinstance(run, dict) else None
    if (
        not isinstance(run, dict)
        or run.get("id") != run_id
        or run.get("path") != _TRUSTED_WORKFLOW
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or not isinstance(run_repository, dict)
        or run_repository.get("full_name") != repository
        or not isinstance(run.get("workflow_id"), int)
        or not isinstance(run.get("run_attempt"), int)
        or run.get("run_attempt", 0) <= 0
    ):
        raise ValueError("selected privileged-review run is not one successful immutable verify run")
    gated_sha = _sha(run.get("head_sha"), label="selected verify run head SHA")
    if gated_sha != expected_gated_sha:
        raise ValueError("selected verify run head SHA differs from the caller release-gate SHA")
    document = _rest(f"/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100", token=token)
    artifacts = document.get("artifacts") if isinstance(document, dict) else None
    expected_name = f"aviato-privileged-review-consumed-{run_id}"
    selected = (
        [item for item in artifacts if isinstance(item, dict) and item.get("name") == expected_name]
        if isinstance(artifacts, list)
        else []
    )
    if not isinstance(document, dict) or document.get("total_count") != len(artifacts or []) or len(selected) != 1:
        raise ValueError("selected verify run does not have one unique consumed-evidence artifact")
    artifact = selected[0]
    workflow_run = artifact.get("workflow_run")
    if (
        artifact.get("expired") is not False
        or not _positive(artifact.get("id"), label="artifact id")
        or not isinstance(artifact.get("size_in_bytes"), int)
        or not 1 <= artifact["size_in_bytes"] <= _MAX_ARTIFACT_BYTES
        or not isinstance(workflow_run, dict)
        or workflow_run.get("id") != run_id
        or workflow_run.get("head_sha") != gated_sha
        or not isinstance(artifact.get("digest"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"]) is None
    ):
        raise ValueError("selected consumed-evidence artifact identity is invalid or expired")
    return VerifiedArtifact(run_id, artifact["id"], expected_name, artifact["digest"], gated_sha)


def extract_git_archive(body: bytes, destination: Path) -> None:
    """Extract a fixed ``git archive`` tar without links or special-file escapes."""

    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    with tarfile.open(fileobj=__import__("io").BytesIO(body), mode="r:") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise ValueError("Git archive contains a link or path traversal")
            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("Git archive regular file is unreadable")
                target.write_bytes(source.read())
                target.chmod(0o755 if member.mode & stat.S_IXUSR else 0o644)
            else:
                raise ValueError("Git archive contains a special file")


def _require_selected_artifact(
    selected: VerifiedArtifact,
    *,
    artifact_id: int | None,
    artifact_digest: str | None,
    label: str,
) -> None:
    if artifact_id != selected.artifact_id or artifact_digest != selected.artifact_digest:
        raise ValueError(f"{label} artifact identity/digest differs from the selected API artifact")


def _require_unchanged_selection(before: VerifiedArtifact, after: VerifiedArtifact) -> None:
    if after != before:
        raise ValueError("verify run/artifact identity changed after fresh live verification")


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")[-2000:]
        raise ValueError(f"fixed approved-release command failed: {command[0]}: {stderr}")
    return result


def _clean_checkout(root: Path, gated_sha: str) -> None:
    head = _run(["/usr/bin/git", "rev-parse", "HEAD"], cwd=root).stdout.decode().strip()
    if head != gated_sha:
        raise ValueError("checked-out source HEAD differs from selected verify run SHA")
    status = _run(["/usr/bin/git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root).stdout
    if status:
        raise ValueError("approved-release source checkout is not clean")


def _canonical_envelope(path: Path) -> dict[str, Any]:
    if path.name != _ENVELOPE_NAME or path.is_symlink() or not path.is_file():
        raise ValueError("downloaded verify artifact must contain one exact consumed envelope file")
    raw = path.read_bytes()
    if not 1 <= len(raw) <= _MAX_ARTIFACT_BYTES:
        raise ValueError("downloaded consumed envelope size is invalid")
    try:
        envelope = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("downloaded consumed envelope is not JSON") from exc
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if raw != canonical or not isinstance(envelope, dict):
        raise ValueError("downloaded consumed envelope is not canonical")
    return envelope


def _verify_downloaded_artifact(envelope_path: Path) -> dict[str, Any]:
    digest_path = envelope_path.with_name(_ENVELOPE_DIGEST_NAME)
    files = sorted(path.name for path in envelope_path.parent.iterdir()) if envelope_path.parent.is_dir() else []
    if files != sorted([_ENVELOPE_NAME, _ENVELOPE_DIGEST_NAME]) or digest_path.is_symlink():
        raise ValueError("downloaded API-digested verify artifact does not contain two exact bound files")
    digest = digest_path.read_text(encoding="ascii")
    expected = "sha256:" + hashlib.sha256(envelope_path.read_bytes()).hexdigest() + "\n"
    if digest != expected:
        raise ValueError("downloaded consumed-envelope bytes differ from the artifact-bound digest")
    return _canonical_envelope(envelope_path)


def _metadata(path: Path) -> tuple[str, str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            if any(
                PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in archive.namelist()
            ):
                raise ValueError(f"{path.name} contains an unsafe archive path")
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError(f"{path.name} has ambiguous core metadata")
            body = archive.read(names[0])
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                pure = PurePosixPath(member.name)
                if pure.is_absolute() or ".." in pure.parts or member.issym() or member.islnk():
                    raise ValueError(f"{path.name} contains an unsafe archive member")
            members = [
                member
                for member in archive.getmembers()
                if member.isfile() and member.name.endswith("/PKG-INFO") and member.name.count("/") == 1
            ]
            if len(members) != 1 or (handle := archive.extractfile(members[0])) is None:
                raise ValueError(f"{path.name} has ambiguous core metadata")
            body = handle.read()
    else:
        raise ValueError(f"unsupported approved distribution archive: {path.name}")
    metadata = email.parser.BytesParser().parsebytes(body)
    name, version = metadata.get("Name"), metadata.get("Version")
    if not name or not version:
        raise ValueError(f"{path.name} core metadata omitted name/version")
    return name, version


def _assert_archive_payload(path: Path, manifest: bytes, envelope: bytes) -> None:
    expected = {
        "aviato/library/privileged-execution-manifest.json": manifest,
        "aviato/library/privileged-review-attestation.json": envelope,
    }
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            matched: dict[str, bytes] = {}
            counts = {suffix: 0 for suffix in expected}
            for info in archive.infolist():
                pure = PurePosixPath(info.filename)
                mode = info.external_attr >> 16
                if pure.is_absolute() or ".." in pure.parts or stat.S_ISLNK(mode):
                    raise ValueError(f"{path.name} contains an unsafe member")
                if not info.is_dir() and mode and not stat.S_ISREG(mode):
                    raise ValueError(f"{path.name} contains a non-regular member")
                if not info.is_dir() and mode and stat.S_IMODE(mode) not in {0o644, 0o755}:
                    raise ValueError(f"{path.name} contains a non-canonical file mode")
                for suffix in expected:
                    if info.filename.endswith(suffix):
                        counts[suffix] += 1
                    if info.filename == suffix:
                        matched[suffix] = archive.read(info)
    else:
        with tarfile.open(path, "r:*") as archive:
            matched = {}
            counts = {suffix: 0 for suffix in expected}
            for member in archive.getmembers():
                pure = PurePosixPath(member.name)
                if pure.is_absolute() or ".." in pure.parts or not (member.isdir() or member.isfile()):
                    raise ValueError(f"{path.name} contains an unsafe or special member")
                if member.isfile() and stat.S_IMODE(member.mode) not in {0o644, 0o755}:
                    raise ValueError(f"{path.name} contains a non-canonical file mode")
                for suffix in expected:
                    if member.name.endswith("/" + suffix):
                        counts[suffix] += 1
                        handle = archive.extractfile(member)
                        if handle is None:
                            raise ValueError(f"{path.name} approved payload is unreadable")
                        matched[suffix] = handle.read()
    if matched != expected or any(count != 1 for count in counts.values()):
        raise ValueError(f"{path.name} does not carry the exact approved runtime manifest/envelope")
    loaded = json.loads(envelope)
    evidence = loaded.get("evidence") if isinstance(loaded, dict) else None
    if (
        not isinstance(loaded, dict)
        or loaded.get("schema") != "aviato-privileged-review-envelope/v1"
        or not isinstance(evidence, dict)
        or evidence.get("status") != "approved"
        or evidence.get("lifecycle") != "consumed"
    ):
        raise ValueError("runtime privileged-review attestation is pending or not one consumed envelope")


def build_approved_release(
    *,
    root: Path,
    repository: str,
    verify_run_id: int,
    expected_gated_sha: str,
    expected_artifact_id: int | None,
    expected_artifact_digest: str | None,
    envelope_path: Path,
    output_dir: Path,
) -> tuple[str, str]:
    token = os.environ.get(_TOKEN_ENV, "")
    if not token or any(character.isspace() for character in token):
        raise ValueError(f"{_TOKEN_ENV} must hold one dedicated verifier App token")
    selected = select_verified_artifact(repository, verify_run_id, expected_gated_sha=expected_gated_sha, token=token)
    _require_selected_artifact(
        selected,
        artifact_id=expected_artifact_id,
        artifact_digest=expected_artifact_digest,
        label="downloaded",
    )
    _clean_checkout(root, selected.gated_sha)
    envelope = _verify_downloaded_artifact(envelope_path)
    evidence = envelope.get("evidence") if isinstance(envelope, dict) else None
    pull = evidence.get("pull_request") if isinstance(evidence, dict) else None
    if not isinstance(pull, dict) or pull.get("merged_sha") != selected.gated_sha:
        raise ValueError("signed evidence merged SHA differs from the selected verify run/gated SHA")
    workflow_document = _rest(f"/repos/{repository}/contents/{_TRUSTED_WORKFLOW}?ref={selected.gated_sha}", token=token)
    workflow_body, workflow_blob_sha = _decode_content(workflow_document, label="approved-review workflow")
    local_workflow = root / _TRUSTED_WORKFLOW
    if local_workflow.read_bytes() != workflow_body:
        raise ValueError("live selected workflow bytes differ from the clean gated checkout")
    signed_workflow = evidence.get("workflow") if isinstance(evidence, dict) else None
    if not isinstance(signed_workflow, dict) or signed_workflow.get("blob_sha") != workflow_blob_sha:
        raise ValueError("signed evidence does not bind the selected protected workflow blob")
    errors = verify_signed_envelope(envelope)
    if errors:
        raise ValueError("fresh privileged-review verification failed: " + "; ".join(errors))
    postverify = select_verified_artifact(repository, verify_run_id, expected_gated_sha=selected.gated_sha, token=token)
    _require_unchanged_selection(selected, postverify)
    _require_selected_artifact(
        postverify,
        artifact_id=expected_artifact_id,
        artifact_digest=expected_artifact_digest,
        label="postverify",
    )
    os.environ.pop(_TOKEN_ENV, None)
    _clean_checkout(root, selected.gated_sha)
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("approved release output directory must not already exist")
    output_dir.mkdir(mode=0o700, parents=True)
    with tempfile.TemporaryDirectory(prefix="aviato-approved-release-") as temporary:
        temp = Path(temporary)
        try:
            temp.resolve().relative_to(root.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("approved source export must be outside the clean checkout")
        archive = _run(["/usr/bin/git", "archive", "--format=tar", selected.gated_sha], cwd=root).stdout
        export = temp / "source"
        extract_git_archive(archive, export)
        overlay = temp / "overlay"
        overlay.mkdir()
        clean_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "LANG": "C"}
        # Overlay generation is itself a fresh privileged-evidence verification.
        # Give only that protected subprocess the verifier token; the package
        # build below receives the deliberately token-free environment.
        overlay_env = clean_env | {_TOKEN_ENV: token}
        _run(
            [
                sys.executable,
                str(root / "scripts/build-approved-release.py"),
                "--generate-overlay-only",
                "--source-root",
                str(root),
                "--approved-envelope",
                str(envelope_path),
                "--overlay-dir",
                str(overlay),
            ],
            cwd=root,
            env=overlay_env,
        )
        library = export / "aviato/library"
        shutil.copyfile(overlay / "privileged-execution-manifest.json", library / "privileged-execution-manifest.json")
        shutil.copyfile(overlay / "privileged-review-attestation.json", library / "privileged-review-attestation.json")
        overlay_manifest = (overlay / "privileged-execution-manifest.json").read_bytes()
        overlay_envelope = (overlay / "privileged-review-attestation.json").read_bytes()
        _run([sys.executable, "-m", "build", "--outdir", str(output_dir)], cwd=export, env=clean_env)
    archives = sorted(path for path in output_dir.iterdir() if path.is_file())
    if len(archives) != 2 or sum(path.suffix == ".whl" for path in archives) != 1:
        raise ValueError("approved build must produce exactly one wheel and one source archive")
    identities = {_metadata(path) for path in archives}
    if len(identities) != 1:
        raise ValueError("approved wheel/source archive identities disagree")
    name, version = identities.pop()
    for archive_path in archives:
        _assert_archive_payload(archive_path, overlay_manifest, overlay_envelope)
    with tempfile.TemporaryDirectory(prefix="aviato-wheel-readiness-") as venv:
        _run([sys.executable, "-m", "venv", venv], cwd=root, env={"PATH": os.environ.get("PATH", "")})
        python = Path(venv) / "bin/python"
        wheel = next(path for path in archives if path.suffix == ".whl")
        _run([str(python), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], cwd=root)
        _run([str(python), "-I", "-c", "import aviato; from aviato import cli"], cwd=root)
        _run([str(Path(venv) / "bin/aviato"), "--help"], cwd=root)
    _clean_checkout(root, selected.gated_sha)
    return name, version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-approved-release.py")
    parser.add_argument("--repository")
    parser.add_argument("--verify-run-id", type=int)
    parser.add_argument("--expected-gated-sha")
    parser.add_argument("--expected-artifact-id", type=int)
    parser.add_argument("--expected-artifact-digest")
    parser.add_argument("--approved-envelope", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--generate-overlay-only", action="store_true")
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--overlay-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.select_only:
            token = os.environ.get(_TOKEN_ENV, "")
            if not token or args.repository is None or args.verify_run_id is None or args.expected_gated_sha is None:
                raise ValueError("artifact selection requires token, repository, run, and gated SHA")
            selected = select_verified_artifact(
                args.repository, args.verify_run_id, expected_gated_sha=args.expected_gated_sha, token=token
            )
            if args.github_output is None:
                raise ValueError("artifact selection requires --github-output")
            with args.github_output.open("a", encoding="utf-8") as output:
                print(f"artifact-id={selected.artifact_id}", file=output)
                print(f"artifact-digest={selected.artifact_digest}", file=output)
                print(f"gated-sha={selected.gated_sha}", file=output)
            return 0
        if args.generate_overlay_only:
            if args.approved_envelope is None or args.overlay_dir is None:
                raise ValueError("overlay generation requires envelope and output directory")
            script = args.source_root / "scripts/regen-privileged-execution-manifest.py"
            _run(
                [
                    sys.executable,
                    str(script),
                    "--approved-envelope",
                    str(args.approved_envelope),
                    "--package-output-dir",
                    str(args.overlay_dir),
                ],
                cwd=args.source_root,
            )
            return 0
        required = (
            args.repository,
            args.verify_run_id,
            args.expected_gated_sha,
            args.expected_artifact_id,
            args.expected_artifact_digest,
            args.approved_envelope,
            args.output_dir,
        )
        if any(item is None for item in required):
            raise ValueError("approved build requires repository, run, SHA, envelope, and output directory")
        name, version = build_approved_release(
            root=args.source_root.resolve(),
            repository=args.repository,
            verify_run_id=args.verify_run_id,
            expected_gated_sha=args.expected_gated_sha,
            expected_artifact_id=args.expected_artifact_id,
            expected_artifact_digest=args.expected_artifact_digest,
            envelope_path=args.approved_envelope.resolve(),
            output_dir=args.output_dir.resolve(),
        )
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8") as output:
                print("artifact-name=aviato-pypi-dist", file=output)
                print(f"distribution-name={name}", file=output)
                print(f"package-version={version}", file=output)
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
