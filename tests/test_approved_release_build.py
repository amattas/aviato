from __future__ import annotations

import copy
import hashlib
import io
import json
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from aviato.core.onboarding import resolved_artifacts
from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT
from aviato.validation import _TEMPLATE_EXAMPLE_VARS

ROOT = Path(__file__).parents[1]


def _workflow() -> dict[str, Any]:
    loaded = yaml.safe_load((ROOT / ".github/workflows/reusable-pypi-publish.yml").read_text())
    assert isinstance(loaded, dict)
    return loaded


def _on(workflow: dict[str, Any]) -> dict[str, Any]:
    loaded = workflow.get("on")
    if loaded is None:
        loaded = cast(dict[object, Any], workflow).get(True)
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def _rendered_caller() -> dict[str, Any]:
    artifacts = resolved_artifacts(
        Registry(MODULE_SOURCE_ROOT),
        "python-library",
        _TEMPLATE_EXAMPLE_VARS["python-library"],
        pin="1",
        docs=False,
    )
    body = next(item.body for item in artifacts if item.output == ".github/workflows/aviato-ci.yml")
    loaded = yaml.safe_load(body)
    assert isinstance(loaded, dict)
    return loaded


def _run(*, head_sha: str = "a" * 40) -> dict[str, Any]:
    return {
        "id": 500,
        "path": ".github/workflows/aviato-privileged-review.yml",
        "head_branch": "main",
        "head_sha": head_sha,
        "event": "workflow_dispatch",
        "workflow_id": 501,
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "repository": {"id": 123, "full_name": "amattas/aviato"},
    }


def _artifact(artifact_id: int = 700) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "name": "aviato-privileged-review-consumed-500",
        "expired": False,
        "size_in_bytes": 50_000,
        "digest": "sha256:" + "d" * 64,
        "workflow_run": {"id": 500, "head_sha": "a" * 40},
    }


def test_reusable_pypi_has_self_only_approved_mode_and_generic_default() -> None:
    workflow = _workflow()
    inputs = _on(workflow)["workflow_call"]["inputs"]
    assert inputs["approved-review-release"] == {"required": False, "type": "boolean", "default": False}
    assert inputs["approved-review-run-id"] == {"required": False, "type": "string", "default": ""}
    jobs = workflow["jobs"]
    assert set(jobs) == {"require-consumer-publisher", "build", "approved-review-release"}
    assert jobs["build"]["if"] == "${{ inputs.approved-review-release != true }}"
    approved = jobs["approved-review-release"]
    assert approved["if"] == "${{ inputs.approved-review-release == true && github.repository == 'amattas/aviato' }}"
    assert approved["environment"] == "privileged-review"
    assert approved["permissions"] == {"actions": "read", "contents": "read"}
    source = json.dumps(approved)
    assert "AVIATO_VERIFIER_APP_ID" in source and "AVIATO_VERIFIER_APP_PRIVATE_KEY" in source
    assert "scripts/build-approved-release.py" in source
    assert "eval " not in source
    steps = approved["steps"]
    select = next(step for step in steps if step.get("id") == "select")
    download = next(step for step in steps if str(step.get("uses", "")).startswith("actions/download-artifact@"))
    build = next(step for step in steps if step.get("id") == "build")
    assert "--select-only" in select["run"]
    assert download["with"]["artifact-ids"] == "${{ steps.select.outputs.artifact-id }}"
    assert build["env"]["GATED_SHA"] == "${{ inputs.gated-sha }}"
    assert "--expected-artifact-digest" in build["run"]

    outputs = _on(workflow)["workflow_call"]["outputs"]
    for name in ("artifact-name", "distribution-name", "package-version"):
        assert "approved-review-release" in outputs[name]["value"]
        assert "jobs.build.outputs" in outputs[name]["value"]


def test_rendered_self_caller_enables_approved_mode_without_trusting_caller_sha_alone() -> None:
    pypi = _rendered_caller()["jobs"]["pypi"]
    assert pypi["with"]["approved-review-release"] == "${{ github.repository == 'amattas/aviato' }}"
    assert pypi["with"]["approved-review-run-id"] == "${{ vars.AVIATO_PRIVILEGED_REVIEW_RUN_ID }}"
    assert pypi["with"]["gated-sha"] == "${{ needs.release-gate.outputs.gated-sha }}"


def test_selected_verify_run_and_artifact_are_unique_terminal_and_exact_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    from aviato.plugins import approved_release

    run = _run()
    artifacts: dict[str, Any] = {"total_count": 1, "artifacts": [_artifact()]}

    def rest(path: str, *, token: str) -> object:
        assert token == "app-token"
        if path.endswith("/actions/runs/500"):
            return copy.deepcopy(run)
        if path.endswith("/actions/runs/500/artifacts?per_page=100"):
            return copy.deepcopy(artifacts)
        raise AssertionError(path)

    monkeypatch.setattr(approved_release, "_rest", rest)
    selected = approved_release.select_verified_artifact(
        "amattas/aviato", 500, expected_gated_sha="a" * 40, token="app-token"
    )
    assert selected.gated_sha == "a" * 40
    assert selected.artifact_id == 700
    assert selected.artifact_digest == "sha256:" + "d" * 64

    for mutation in (
        lambda: run.update(conclusion="failure"),
        lambda: run.update(head_sha="b" * 40),
        lambda: artifacts["artifacts"].append(_artifact(701)),
    ):
        run.clear()
        run.update(_run())
        artifacts["artifacts"] = [_artifact()]
        mutation()
        with pytest.raises(ValueError):
            approved_release.select_verified_artifact(
                "amattas/aviato", 500, expected_gated_sha="a" * 40, token="app-token"
            )

    with pytest.raises(ValueError, match="digest"):
        approved_release._require_selected_artifact(
            selected, artifact_id=selected.artifact_id, artifact_digest="sha256:" + "0" * 64, label="downloaded"
        )
    changed = approved_release.VerifiedArtifact(
        selected.run_id,
        selected.artifact_id,
        selected.artifact_name,
        "sha256:" + "0" * 64,
        selected.gated_sha,
    )
    with pytest.raises(ValueError, match="changed after"):
        approved_release._require_unchanged_selection(selected, changed)


def test_git_archive_extraction_rejects_links_special_files_and_traversal(tmp_path: Path) -> None:
    from aviato.plugins import approved_release

    for name, kind in (("../escape", "file"), ("link", "symlink"), ("device", "device")):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo(name)
            if kind == "file":
                body = b"body"
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "target"
                archive.addfile(info)
            else:
                info.type = tarfile.CHRTYPE
                archive.addfile(info)
        with pytest.raises(ValueError):
            approved_release.extract_git_archive(stream.getvalue(), tmp_path / kind)


def test_built_archives_require_exact_consumed_runtime_envelope_and_canonical_modes(tmp_path: Path) -> None:
    from aviato.plugins import approved_release

    manifest = b"[]\n"
    envelope = json.dumps(
        {
            "algorithm": "ssh-ed25519",
            "evidence": {"status": "approved", "lifecycle": "consumed"},
            "schema": "aviato-privileged-review-envelope/v1",
            "signature": "c2ln",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    wheel = tmp_path / "aviato-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, body in (
            ("aviato/library/privileged-execution-manifest.json", manifest),
            ("aviato/library/privileged-review-attestation.json", envelope),
        ):
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, body)
    approved_release._assert_archive_payload(wheel, manifest, envelope)

    pending = envelope.replace(b'"consumed"', b'"pending"')
    pending_wheel = tmp_path / "pending.whl"
    with zipfile.ZipFile(pending_wheel, "w") as archive:
        for name, body in (
            ("aviato/library/privileged-execution-manifest.json", manifest),
            ("aviato/library/privileged-review-attestation.json", pending),
        ):
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, body)
    with pytest.raises(ValueError, match="pending"):
        approved_release._assert_archive_payload(pending_wheel, manifest, pending)

    missing = tmp_path / "missing.whl"
    with zipfile.ZipFile(missing, "w") as archive:
        info = zipfile.ZipInfo("aviato/library/privileged-review-attestation.json")
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(info, envelope)
    with pytest.raises(ValueError, match="exact approved"):
        approved_release._assert_archive_payload(missing, manifest, envelope)

    drifted = tmp_path / "drifted.whl"
    with zipfile.ZipFile(drifted, "w") as archive:
        for name, body, mode in (
            ("aviato/library/privileged-execution-manifest.json", b"{}\n", 0o644),
            ("aviato/library/privileged-review-attestation.json", envelope, 0o600),
            ("extra/aviato/library/privileged-review-attestation.json", envelope, 0o644),
        ):
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, body)
    with pytest.raises(ValueError, match="mode|exact approved"):
        approved_release._assert_archive_payload(drifted, manifest, envelope)


def test_builder_rechecks_after_live_verify_exports_outside_checkout_and_tests_installed_wheel() -> None:
    from aviato.plugins import approved_release

    source = Path(approved_release.__file__).read_text()
    assert "verify_signed_envelope(envelope)" in source
    assert "_require_unchanged_selection(selected, postverify)" in source
    assert source.count("_clean_checkout(root, selected.gated_sha)") >= 3
    assert '["/usr/bin/git", "archive", "--format=tar", selected.gated_sha]' in source
    assert "relative_to(root.resolve())" in source
    assert "_assert_archive_payload" in source
    assert '"-m", "venv"' in source
    assert '"pip", "install", "--disable-pip-version-check"' in source
    assert '"bin/aviato"' in source
    assert "overlay_env = clean_env | {_TOKEN_ENV: token}" in source
    assert source.index("overlay_env = clean_env | {_TOKEN_ENV: token}") < source.index('"-m", "build"')
    assert source.index("os.environ.pop(_TOKEN_ENV, None)") < source.index('"-m", "build"')


def test_clean_checkout_rejects_source_mutation_after_verification(tmp_path: Path) -> None:
    from aviato.plugins import approved_release

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "source.py"
    source.write_text("clean\n")
    subprocess.run(["git", "add", "source.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "clean"],
        cwd=tmp_path,
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, text=True, capture_output=True
    ).stdout.strip()
    approved_release._clean_checkout(tmp_path, head)
    source.write_text("mutated\n")
    with pytest.raises(ValueError, match="not clean"):
        approved_release._clean_checkout(tmp_path, head)


def test_downloaded_envelope_bytes_are_bound_inside_the_api_digested_artifact(tmp_path: Path) -> None:
    from aviato.plugins import approved_release

    envelope = tmp_path / "aviato-privileged-review-consumed.json"
    body = json.dumps({"schema": "example"}, sort_keys=True, separators=(",", ":")).encode()
    envelope.write_bytes(body)
    digest = tmp_path / "aviato-privileged-review-consumed.sha256"
    digest.write_text("sha256:" + hashlib.sha256(body).hexdigest() + "\n")
    assert approved_release._verify_downloaded_artifact(envelope) == {"schema": "example"}
    digest.write_text("sha256:" + "0" * 64 + "\n")
    with pytest.raises(ValueError, match="bytes differ"):
        approved_release._verify_downloaded_artifact(envelope)
    digest.unlink()
    with pytest.raises(ValueError, match="two exact"):
        approved_release._verify_downloaded_artifact(envelope)
