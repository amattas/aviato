from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from aviato.core.composition import resolve_profile
from aviato.core.onboarding import resolved_artifacts
from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT, REPO_ROOT
from aviato.validation import _TEMPLATE_EXAMPLE_VARS

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCAFFOLD_FILES = REPO_ROOT / "aviato" / "library" / "scaffold" / "files"
JsonDict = dict[str, Any]


def _load(name: str) -> JsonDict:
    loaded = yaml.safe_load((WORKFLOWS / name).read_text())
    assert isinstance(loaded, dict)
    return loaded


def _on(workflow: JsonDict) -> JsonDict:
    block = workflow.get("on") or cast(dict[object, Any], workflow).get(True)
    assert isinstance(block, dict)
    return block


def _rendered_python_library_workflow() -> JsonDict:
    artifacts = resolved_artifacts(
        Registry(MODULE_SOURCE_ROOT),
        "python-library",
        _TEMPLATE_EXAMPLE_VARS["python-library"],
        pin="1",
        docs=False,
    )
    body = next(a.body for a in artifacts if a.output == ".github/workflows/aviato-ci.yml")
    loaded = yaml.safe_load(body)
    assert isinstance(loaded, dict)
    return loaded


def _rendered_python_library_docs_workflow() -> JsonDict:
    artifacts = resolved_artifacts(
        Registry(MODULE_SOURCE_ROOT),
        "python-library",
        _TEMPLATE_EXAMPLE_VARS["python-library"],
        pin="1",
        docs=True,
    )
    body = next(a.body for a in artifacts if a.output == ".github/workflows/aviato-docs.yml")
    loaded = yaml.safe_load(body)
    assert isinstance(loaded, dict)
    return loaded


def test_serializing_workflows_declare_per_repo_concurrency() -> None:
    # review #4/#26: the scheduled drift run, the release run, and the deploy publishes must
    # SERIALIZE per repo (queue, never cancel) so concurrent runs can't race a force-push / alias
    # move / duplicate publish. Guard the concurrency block structurally.
    for name in (
        "reusable-release.yml",
        "reusable-pypi-publish.yml",
        "reusable-app-store-connect.yml",
        "reusable-docker-ghcr.yml",
        "reusable-docs-pages.yml",
    ):
        wf = _load(name)
        conc = wf.get("concurrency")
        assert isinstance(conc, dict), f"{name} missing top-level concurrency"
        assert "${{ github.repository }}" in conc["group"], f"{name} concurrency not per-repo"
        assert conc.get("cancel-in-progress") is False, f"{name} must queue, not cancel"


def test_release_floating_major_is_monotonic_guarded() -> None:
    # review (floating-major monotonicity): the release workflow must not regress the mutable @N
    # pointer for an out-of-order/older release — the force-move is gated on `is-highest`.
    body = (WORKFLOWS / "reusable-release.yml").read_text()
    assert "aviato is-highest" in body, "floating-major move must be gated on is-highest"
    # the gate must precede the force-push of the major
    assert body.index("aviato is-highest") < body.index('git push -f origin "${major}"')


def test_docs_callers_gate_workflow_run_to_origin_repo() -> None:
    # review #27: a workflow_run runs in the BASE repo with full privileges; the resolve job's
    # privileged checkout must be gated to runs that originated in THIS repo, so fork-PR head code
    # is never checked out in the privileged context.
    docs_callers = sorted(SCAFFOLD_FILES.glob("wf-docs-*.yml"))
    assert docs_callers
    for caller in docs_callers:
        body = caller.read_text(encoding="utf-8")
        assert "head_repository.full_name == github.repository" in body, caller.name


def test_docs_callers_resolve_tolerates_no_tag() -> None:
    # Observed live: `grep -E` exits 1 when the completed run's head carries NO release
    # tag (every ordinary merge), and under `set -euo pipefail` a failing command
    # substitution fails the assignment — the resolve job went red on every non-release
    # run instead of cleanly emitting release=false. The pipeline must end `|| true`.
    docs_callers = sorted(SCAFFOLD_FILES.glob("wf-docs-*.yml"))
    assert docs_callers
    for caller in docs_callers:
        body = caller.read_text(encoding="utf-8")
        assert '| head -n1 || true)"' in body, f"{caller.name}: resolve must tolerate the no-tag case"


def test_docs_callers_resolve_bare_aviato_release_tags() -> None:
    # G2/§13.3: Aviato tags releases as BARE SemVer (`1.2.3`); policy.yml rejects a
    # v-prefix. The docs deploy callers gate on `git tag --list <glob>` to detect a
    # release commit. A v-prefixed glob (`v[0-9]*...`) can NEVER match a real Aviato tag,
    # so docs deploy would silently never run — and these callers have no template/parity
    # coverage, so nothing else catches it. Guard the tag matcher directly.
    docs_callers = sorted(SCAFFOLD_FILES.glob("wf-docs-*.yml"))
    assert docs_callers, "no docs caller scaffolds found"
    for caller in docs_callers:
        body = caller.read_text(encoding="utf-8")
        assert "--list" in body, f"{caller.name} no longer resolves a release tag via git tag --list"
        assert "'v[0-9]" not in body, (
            f"{caller.name} matches a v-prefixed tag glob, which no Aviato release tag ever uses "
            f"(policy rejects the v-prefix) — docs deploy would never trigger"
        )
        assert "--list '[0-9]" in body, f"{caller.name} must match bare-SemVer release tags"


def test_local_install_is_limited_to_structural_library_bootstrap() -> None:
    # §5.10: local-install is only for the Library bootstrapping itself before a
    # released ref exists. A consumer hand-editing local-install:true must fail before
    # `pip install -e .` unless the checkout has the Library anchors and bootstrap:true.
    for name, job_name in (
        # C12-W1: BOTH release jobs install Aviato; each must carry the full guard.
        ("reusable-release.yml", "derive"),
        ("reusable-release.yml", "release"),
    ):
        wf = _load(name)
        install = next(s for s in wf["jobs"][job_name]["steps"] if s.get("name") == "Install Aviato (pinned)")
        run = install["run"]
        for anchor in (
            "aviato/core/__init__.py",
            "aviato/library/bundles",
            "aviato/library/scaffold",
            "aviato/library/policy.yml",
            ".github/aviato.yml",
        ):
            assert anchor in run, f"{name} local install guard missing {anchor}"
        assert "bootstrap: true" in run, f"{name} local install guard must require bootstrap:true"
        assert run.index("local-install is only valid") < run.index("python -m pip install -e .")


_DEPLOY_WORKFLOWS = (
    "reusable-pypi-publish.yml",
    "reusable-docker-ghcr.yml",
    "reusable-docs-pages.yml",
    "reusable-app-store-connect.yml",
)


def test_deploys_consume_the_gated_sha() -> None:
    # C12-W2 (TOCTOU): the gate validates a COMMIT; deploys must consume that commit,
    # not the mutable tag — checkout by gated-sha plus a pre-publish tag→gated-sha
    # re-verify, so a tag force-moved between gate and publish aborts the deploy.
    gate = _load("reusable-release-gate.yml")
    gate_on = _on(gate)
    assert "gated-sha" in (gate_on["workflow_call"].get("outputs") or {}), "gate must export gated-sha"
    for name in _DEPLOY_WORKFLOWS:
        wf = _load(name)
        on_block = _on(wf)
        inputs = on_block["workflow_call"]["inputs"]
        assert inputs.get("gated-sha", {}).get("required") is True, f"{name} must require gated-sha"
        body = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "ref: ${{ inputs.gated-sha }}" in body, f"{name} must check out the gated SHA"
        assert "ref: ${{ inputs.release-tag || github.ref }}" not in body, f"{name} still checks out the mutable tag"
        assert 'git rev-parse "refs/tags/${RELEASE_TAG}^{commit}"' in body, f"{name} missing the tag re-verify"


def test_callers_pass_gated_sha_to_deploys() -> None:
    # Every scaffold caller body that wires a deploy must thread the gate's output —
    # a missed caller ships a consumer whose deploy cannot start (required input).
    for caller in sorted(SCAFFOLD_FILES.glob("wf-*.yml")):
        body = caller.read_text(encoding="utf-8")
        if not any(d in body for d in _DEPLOY_WORKFLOWS):
            continue
        threaded = "gated-sha: ${{ needs.release-gate.outputs.gated-sha }}" in body
        assert threaded, f"{caller.name} wires a deploy without threading the gated SHA (C12-W2)"


def _release_gate_step(name: str) -> JsonDict:
    workflow = _load("reusable-release-gate.yml")
    return next(step for step in workflow["jobs"]["gate"]["steps"] if step.get("name") == name)


def test_release_gate_resolves_release_tag_commit_for_descendant_event_sha(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    remote = tmp_path / "remote.git"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Aviato Test"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "aviato@example.invalid"], cwd=repository, check=True)

    tracked = repository / "tracked.txt"
    tracked.write_text("release\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "release"], cwd=repository, check=True, capture_output=True)
    release_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "tag", "1.2.3"], cwd=repository, check=True)

    tracked.write_text("release\ndescendant\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "descendant"], cwd=repository, check=True, capture_output=True)
    event_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert event_sha != release_sha

    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repository, check=True)
    subprocess.run(["git", "push", "--set-upstream", "origin", "main", "--tags"], cwd=repository, check=True)

    output = tmp_path / "github-output"
    resolve = _release_gate_step("Resolve gated commit")
    resolve_env = {
        **os.environ,
        "GITHUB_OUTPUT": str(output),
        "GITHUB_SHA": event_sha,
        "RELEASE_TAG_INPUT": "1.2.3",
        "RESOLVED_TAG": "1.2.3",
    }
    subprocess.run(["bash", "-c", resolve["run"]], cwd=repository, env=resolve_env, check=True)
    gated_sha = dict(line.split("=", 1) for line in output.read_text().splitlines())["gated-sha"]
    assert gated_sha == release_sha

    verify = _release_gate_step("Verify tag points at default branch")
    verify_env = {
        **os.environ,
        "DEFAULT_BRANCH": "main",
        "GATED_SHA": gated_sha,
        "RESOLVED_TAG": "1.2.3",
    }
    subprocess.run(["bash", "-c", verify["run"]], cwd=repository, env=verify_env, check=True)


def test_release_gate_threads_resolved_sha_through_later_queries() -> None:
    workflow = _load("reusable-release-gate.yml")
    steps = workflow["jobs"]["gate"]["steps"]
    resolve_index = next(i for i, step in enumerate(steps) if step.get("name") == "Resolve gated commit")
    later_steps = steps[resolve_index + 1 :]
    for step in later_steps:
        assert "GITHUB_SHA" not in step.get("run", ""), f"{step.get('name')} reuses raw event identity"

    output_expression = "${{ steps.resolve-gated-sha.outputs.gated-sha }}"
    for name in (
        "Verify tag points at default branch",
        "Require merged pull request",
        "Require successful workflow",
    ):
        step = next(candidate for candidate in later_steps if candidate.get("name") == name)
        assert step.get("env", {}).get("GATED_SHA") == output_expression, f"{name} must consume gated-sha"


def test_release_gate_gated_sha_shell_names_do_not_trigger_shellcheck_sc2153() -> None:
    verify = _release_gate_step("Verify tag points at default branch")
    script = str(verify["run"])

    assert 'gated_sha="$(git rev-parse "${GATED_SHA}^{commit}")"' not in script
    assert 'gated_commit="$(git rev-parse "${GATED_SHA}^{commit}")"' in script


def test_language_ci_contract_parity() -> None:
    # §2.14 (finding 27): every language CI exposes the SAME command contract —
    # unsupported steps carry an empty command + disabled default, never a missing input.
    expected = {
        "working-directory",
        "install-command",
        "lint-command",
        "format-command",
        "typecheck-command",
        "test-command",
        "build-command",
        "run-install",
        "run-lint",
        "run-format",
        "run-typecheck",
        "run-tests",
        "run-build",
    }
    for name in ("reusable-python-ci.yml", "reusable-node-ci.yml", "reusable-swift-ci.yml"):
        wf = _load(name)
        on_block = _on(wf)
        inputs = set(on_block["workflow_call"]["inputs"])
        missing = expected - inputs
        assert not missing, f"{name} missing shared-contract inputs: {sorted(missing)}"


def test_node_ci_gates_fail_loud_without_if_present() -> None:
    # finding 29: a consumer deleting the lint/test script from the operator-owned
    # manifest must FAIL the verify gate, not silently skip it.
    wf = _load("reusable-node-ci.yml")
    on_block = _on(wf)
    inputs = on_block["workflow_call"]["inputs"]
    assert inputs["lint-command"]["default"] == "npm run lint"
    assert inputs["test-command"]["default"] == "npm test"


def test_docs_retention_defaults_to_keep_all() -> None:
    # finding 37 (operator decision): every released version's docs are kept by default.
    # The Zensical/mike rewrite gates the ENTIRE prune snippet behind `RETENTION -gt 0`
    # rather than special-casing cap<=0 inside the python pruner — 0 (the default) means
    # the prune step never runs at all, so no version is ever removed.
    wf = _load("reusable-docs-pages.yml")
    on_block = _on(wf)
    assert on_block["workflow_call"]["inputs"]["docs-retention"]["default"] == 0
    body = (WORKFLOWS / "reusable-docs-pages.yml").read_text(encoding="utf-8")
    assert 'if [ "${RETENTION}" -gt 0 ]' in body, "prune snippet must be gated on RETENTION -gt 0"
    guard_pos = body.index('if [ "${RETENTION}" -gt 0 ]')
    prune_pos = body.index('"mike", "delete"')
    assert guard_pos < prune_pos, "the -gt 0 keep-all guard must precede the prune logic"


def test_docs_pages_deploy_is_opt_in_and_consumes_exact_branch_artifact() -> None:
    wf = _load("reusable-docs-pages.yml")
    on_block = _on(wf)
    serve = on_block["workflow_call"]["inputs"]["serve-pages"]
    assert serve["required"] is False
    assert serve["type"] == "boolean"
    assert serve["default"] is False

    build = wf["jobs"]["build"]
    push = wf["jobs"]["push"]
    deploy = wf["jobs"]["deploy"]
    assert build["permissions"] == {"contents": "read", "pages": "read"}
    assert push["permissions"] == {"contents": "write"}
    assert "if" not in push, "serve-pages=false must still push the canonical docs branch"
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    assert set(deploy["needs"]) == {"build", "push"}
    assert "inputs.serve-pages" in str(deploy["if"])
    assert "success()" in str(deploy["if"])
    assert deploy["environment"] == {
        "name": "github-pages",
        "url": "${{ steps.deployment.outputs.page_url }}",
    }
    assert deploy["steps"] == [
        {
            "name": "Deploy GitHub Pages",
            "id": "deployment",
            "uses": "actions/deploy-pages@v5",
        }
    ], "the privileged deploy job must execute no consumer commands"

    steps = build["steps"]
    materialize = next(step for step in steps if step.get("name") == "Materialize exact docs branch tree")
    body = materialize["run"]
    assert "refs/heads/${DOCS_BRANCH}" in body
    assert "git archive" in body
    assert "symlink" in body.lower()
    # Regression (§13.3 live-proof finding): `git archive` with no explicit pathspec,
    # run from the job's docs working-directory (root "." since the root-layout docs move),
    # implicitly scopes the archive to that subdirectory WITHIN the target tree-ish.
    # docs-branch is an orphan branch with a flat layout that has no such subdirectory,
    # so this silently produced an EMPTY Pages artifact for any non-root docs layout —
    # no error, no non-zero exit, every job reports green. Always archive from the
    # repository root regardless of the job's working-directory default.
    assert 'git -C "${GITHUB_WORKSPACE}" archive "refs/heads/${DOCS_BRANCH}"' in body
    configure = next(step for step in steps if str(step.get("uses", "")).startswith("actions/configure-pages@"))
    upload = next(step for step in steps if str(step.get("uses", "")).startswith("actions/upload-pages-artifact@"))
    assert "inputs.serve-pages" in str(configure["if"])
    assert "inputs.serve-pages" in str(upload["if"])
    assert upload["with"]["path"] == "/tmp/aviato-pages-site"

    assert wf["concurrency"]["cancel-in-progress"] is False


def test_rendered_consumer_docs_caller_defaults_pages_off_and_grants_only_call_union() -> None:
    caller = _rendered_python_library_docs_workflow()
    docs = caller["jobs"]["docs"]
    # Root-layout docs (commit 8758059): zensical.toml + docs/ live at the repo root, so the
    # docs job runs from "." and points the toolchain install at requirements-docs.txt (the
    # reusable default is requirements.txt, so the caller must pass the new name explicitly).
    assert docs["with"]["working-directory"] == "."
    assert docs["with"]["docs-requirements"] == "requirements-docs.txt"
    assert docs["with"]["serve-pages"] is False
    assert docs["permissions"] == {
        "contents": "write",
        "pages": "write",
        "id-token": "write",
    }


# Both the starter master and Aviato's own copy of it share one contract.
_DOCS_SITE_WORKFLOWS = ["starter/docs-site/docs.yml", ".github/workflows/docs.yml"]


@pytest.mark.parametrize("rel_path", _DOCS_SITE_WORKFLOWS)
def test_docs_site_single_job_pushes_versioned_branch_only(rel_path: str) -> None:
    body = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    wf = yaml.safe_load(body)
    assert wf["permissions"] == {}
    assert wf["concurrency"]["cancel-in-progress"] is False
    assert "${{ github.repository }}" in wf["concurrency"]["group"]
    # Classic mike setup: one job pushes versions to the docs branch and Pages
    # serves that branch directly — no artifact upload/deploy jobs, and the
    # branch-writing job is the only privilege holder.
    assert set(wf["jobs"]) == {"docs"}
    assert wf["jobs"]["docs"]["permissions"] == {"contents": "write"}
    assert 'mike deploy --push --branch "${DOCS_BRANCH}"' in body
    assert "upload-pages-artifact" not in body
    assert "deploy-pages" not in body


@pytest.mark.parametrize("rel_path", _DOCS_SITE_WORKFLOWS)
def test_docs_site_invalid_tag_skips_every_publish_step(rel_path: str, tmp_path: Path) -> None:
    starter = yaml.safe_load((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
    steps = starter["jobs"]["docs"]["steps"]
    release_index = next(i for i, step in enumerate(steps) if step.get("id") == "release")
    release = steps[release_index]
    for step in steps[release_index + 1 :]:
        assert "steps.release.outputs.publish == 'true'" in str(step.get("if", "")), step

    output = tmp_path / "github-output"
    env = os.environ | {
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REF_TYPE": "tag",
        "GITHUB_REF_NAME": "1foo.2bar.3baz",
    }
    result = subprocess.run(["bash", "-c", release["run"]], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8").splitlines() == ["publish=false"]


@pytest.mark.parametrize("rel_path", _DOCS_SITE_WORKFLOWS)
@pytest.mark.parametrize(
    ("ref_type", "ref_name", "input_version", "expected"),
    [
        ("tag", "1.2.3", "", ["publish=true", "tag=1.2.3"]),
        ("branch", "main", "", ["publish=true", "tag="]),
        # workflow_dispatch seeding: an explicit version input publishes like a tag …
        ("branch", "main", "1.2.3", ["publish=true", "tag=1.2.3"]),
        # … and a malformed one skips every publish step, same as a bad tag.
        ("branch", "main", "not-a-version", ["publish=false"]),
    ],
)
def test_docs_site_valid_refs_publish(
    rel_path: str, ref_type: str, ref_name: str, input_version: str, expected: list[str], tmp_path: Path
) -> None:
    starter = yaml.safe_load((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
    release = next(step for step in starter["jobs"]["docs"]["steps"] if step.get("id") == "release")
    output = tmp_path / "github-output"
    env = os.environ | {
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REF_TYPE": ref_type,
        "GITHUB_REF_NAME": ref_name,
        "INPUT_VERSION": input_version,
    }
    result = subprocess.run(["bash", "-c", release["run"]], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8").splitlines() == expected


def test_registry_publishes_run_in_deployment_environments() -> None:
    # finding 7: PyPI/GHCR publishes get the same platform-level environment gate the
    # Pages/App Store deploys already have.
    caller = _rendered_python_library_workflow()
    assert caller["jobs"]["pypi-publish"]["environment"] == "pypi"
    ghcr = _load("reusable-docker-ghcr.yml")
    assert ghcr["jobs"]["docker"]["environment"]["name"] == "${{ inputs.environment-name }}"


def test_pypi_reusable_only_builds_vetted_artifact_and_local_caller_publishes() -> None:
    reusable = _load("reusable-pypi-publish.yml")
    reusable_body = (WORKFLOWS / "reusable-pypi-publish.yml").read_text(encoding="utf-8")
    assert set(reusable["jobs"]) == {"require-consumer-publisher", "build"}
    assert "pypa/gh-action-pypi-publish" not in reusable_body
    assert "id-token: write" not in reusable_body
    assert "attest-build-provenance" not in reusable_body
    assert reusable["jobs"]["build"]["permissions"] == {"contents": "read"}
    upload = next(step for step in reusable["jobs"]["build"]["steps"] if step.get("name") == "Upload build artifacts")
    assert upload["uses"] == "actions/upload-artifact@v7"
    assert upload["with"]["name"] == "aviato-pypi-dist"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] == 1

    caller_body = (SCAFFOLD_FILES / "wf-python-library.yml").read_text(encoding="utf-8")
    assert "consumer-publisher-present: true" in caller_body
    assert "pypa/gh-action-pypi-publish@ba38be9e461d3875417946c167d0b5f3d385a247" in caller_body
    assert "actions/download-artifact@v8" in caller_body
    assert "environment: pypi" in caller_body
    assert "id-token: write" in caller_body and "attestations: write" in caller_body
    caller = _rendered_python_library_workflow()
    assert "id-token" not in (caller.get("permissions") or {})
    assert "attestations" not in (caller.get("permissions") or {})
    for job_name, job in caller["jobs"].items():
        if job_name == "pypi-publish" or not isinstance(job, dict):
            continue
        permissions = job.get("permissions") or {}
        assert permissions.get("id-token") != "write", job_name
        assert permissions.get("attestations") != "write", job_name
    publish_body = caller_body[caller_body.index("  pypi-publish:") :]
    assert '"repos/${GITHUB_REPOSITORY}/git/ref/tags/${RELEASE_TAG}"' in publish_body
    assert "${{ needs.release-gate.outputs.gated-sha }}" in publish_body
    assert "eval " not in publish_body
    assert "pip install" not in publish_body
    assert "python -m build" not in publish_body


def test_pypi_stale_caller_fails_before_build_with_sync_instruction() -> None:
    reusable = _load("reusable-pypi-publish.yml")
    on_block = _on(reusable)
    marker = on_block["workflow_call"]["inputs"]["consumer-publisher-present"]
    assert marker["required"] is False
    assert marker["type"] == "boolean"
    assert marker["default"] is False
    guard = reusable["jobs"]["require-consumer-publisher"]
    reject = guard["steps"][0]
    assert reject["if"] == "${{ inputs.consumer-publisher-present != true }}"
    assert "aviato sync" in reject["run"]
    assert reusable["jobs"]["build"]["needs"] == "require-consumer-publisher"


def _single_python_heredoc(run: str) -> str:
    match = re.search(r"<<'PY'\n(?P<body>.*?)\nPY", run, flags=re.DOTALL)
    assert match is not None, "step does not contain a quoted Python heredoc"
    return match.group("body")


def test_pypi_simple_index_endpoint_mapping_is_validated_and_testpypi_safe() -> None:
    caller = _rendered_python_library_workflow()
    steps = caller["jobs"]["pypi-publish"]["steps"]
    resolver = next(step for step in steps if step.get("name") == "Resolve simple index endpoint")
    script = _single_python_heredoc(resolver["run"])

    testpypi = subprocess.run(
        ["python", "-c", script, "https://test.pypi.org/legacy/", ""],
        text=True,
        capture_output=True,
        check=True,
    )
    assert testpypi.stdout.strip() == "https://test.pypi.org/simple/"

    for upload, simple in (
        ("http://test.pypi.org/legacy/", ""),
        ("https://user:secret@test.pypi.org/legacy/", ""),
        ("https://test.pypi.org/unsupported/", ""),
        ("", "https://test.pypi.org/not-simple/"),
    ):
        result = subprocess.run(["python", "-c", script, upload, simple], text=True, capture_output=True)
        assert result.returncode != 0, (upload, simple)


def test_pypi_publisher_uses_pep691_hash_confirmation_without_package_execution() -> None:
    caller = _rendered_python_library_workflow()
    publisher = caller["jobs"]["pypi-publish"]
    shell = "\n".join(str(step.get("run", "")) for step in publisher["steps"])
    for forbidden in (
        "python -m pip",
        "pip download",
        "pip install",
        "python -m build",
        "setup.py",
        "pyproject.toml",
        "eval ",
        " uv ",
        "poetry ",
        "npm ",
        "yarn ",
        "pnpm ",
    ):
        assert forbidden not in shell, f"publisher shell executes forbidden command/content: {forbidden!r}"
    confirm = next(step for step in publisher["steps"] if step.get("name") == "Confirm published artifacts")
    run = confirm["run"]
    assert "application/vnd.pypi.simple.v1+json" in run
    assert "urllib.request" in run
    assert "hashlib.sha256" in run
    assert "files" in run and "filename" in run and "hashes" in run
    # pypa/gh-action-pypi-publish >= 1.14 drops *.publish.attestation sidecars into dist/
    # during upload; confirmation must hash only real distributions or it false-negatives
    # against the simple index, which never lists sidecars (live 0.4.0 publish failure).
    assert 'path.name.endswith((".whl", ".tar.gz"))' in run
    assert "EXPECTED_VERSION" in confirm["env"]
    assert "DISTRIBUTION_NAME" in confirm["env"]


def test_pypi_publisher_rechecks_fresh_remote_tag_after_download_and_before_publish() -> None:
    caller = _rendered_python_library_workflow()
    steps = caller["jobs"]["pypi-publish"]["steps"]
    names = [step["name"] for step in steps]
    download = names.index("Download vetted build artifacts")
    first = names.index("Verify fresh remote tag after artifact download")
    attest = names.index("Attest build provenance")
    final = names.index("Final fresh remote tag verification")
    publish = names.index("Publish distributions")
    alternate = names.index("Publish distributions to alternate repository")
    assert download < first < attest < final < publish < alternate
    assert final + 1 == publish
    for index in (first, final):
        step = steps[index]
        assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
        assert "gh api" in step["run"]
        assert "/git/ref/tags/" in step["run"]
        assert "/git/tags/" in step["run"], "annotated tags must be peeled"
        assert "git rev-parse" not in step["run"]


def test_ghcr_publishes_only_scanned_digests() -> None:
    # C12-W3: no rebuild between scan and publish — the workflow must scan local OCI
    # archives and promote those exact bytes by digest, asserting pushed == scanned.
    body = (WORKFLOWS / "reusable-docker-ghcr.yml").read_text(encoding="utf-8")
    assert "docker/build-push-action" not in body, "scan-then-rebuild reintroduced (C12-W3)"
    assert '--output "type=oci,dest=oci/${slug}.tar"' in body, "build must emit a local OCI archive"
    assert "skopeo copy --digestfile" in body, "push must promote the archive bytes"
    assert '"${pushed_digest}" != "${local_digest}"' in body, "pushed==scanned digest assert missing"
    assert body.index("trivy image") < body.index("skopeo copy"), "scan must precede push"

    # Trivy >=0.72 (aquasecurity/setup-trivy pinned to v0.72.0) can no longer auto-detect
    # a buildx `type=oci,dest=...` archive passed directly via `--input` (it neither parses
    # as a docker-save tar nor as an OCI layout dir) — extract the archive bytes to a real
    # OCI layout DIRECTORY first and point every trivy invocation at that directory instead.
    extract_cmd = 'tar -xf "oci/${slug}.tar" -C "oci/${slug}.layout"'
    assert extract_cmd in body, "must extract the buildx OCI archive to a layout dir (Trivy >=0.72)"
    assert '--input "oci/${slug}.tar"' not in body, "trivy must not be pointed at the raw tar (Trivy >=0.72 regression)"
    trivy_input_count = body.count('--input "oci/${slug}.layout"')
    assert trivy_input_count == 3, f"all 3 trivy calls must use the layout dir, got {trivy_input_count}"

    # Per-arch code-scanning categories: without a per-platform automationDetails.id stamp,
    # every SARIF shares the auto category (workflow:job) and the single upload-sarif step
    # rejects the second file for the same commit, so a multi-platform release can never
    # complete (live §13.2 proof finding, 2026-07-18).
    stamp = """jq --arg cat "aviato-docker/${slug}" '.runs[0].automationDetails.id = $cat'"""
    assert stamp in body, "each platform SARIF must be stamped with a per-arch category"
    sarif_index = body.index('--format sarif --output "trivy-sarif/${slug}.sarif"')
    assert sarif_index < body.index(stamp), "the stamp must run after the SARIF is written"

    extract_index = body.index(extract_cmd)
    build_index = body.index('--output "type=oci,dest=oci/${slug}.tar"')
    first_trivy_index = body.index('--input "oci/${slug}.layout"')
    assert build_index < extract_index < first_trivy_index, "buildx writes the tar, then extract, then trivy scans"

    # skopeo must still promote the UNTOUCHED tar (not the extracted layout dir) — the
    # extraction is scan-input-only plumbing and must not affect C12-W3 byte identity.
    assert "skopeo inspect --format '{{.Digest}}' \"oci-archive:oci/${slug}.tar\"" in body
    assert 'skopeo copy --digestfile "oci/${slug}.pushed" \\\n              "oci-archive:oci/${slug}.tar"' in body


def test_non_pushing_checkouts_do_not_persist_credentials() -> None:
    # finding 6: the job token must not sit in .git/config while consumer/build code
    # runs. Only workflows that legitimately push (or fetch) from the checkout keep
    # credentials. Only the exact write jobs that deliberately push a known ref may
    # retain them: the release write job and the isolated docs-branch push job.
    credentialed_push_jobs = {
        ("reusable-release.yml", "release"),
        ("reusable-docs-pages.yml", "push"),
        # Aviato's own starter-style docs caller: mike pushes gh-pages from its checkout.
        ("docs.yml", "docs"),
    }
    for path in sorted(WORKFLOWS.glob("*.yml")):
        wf = _load(path.name)
        for job_name, job in (wf.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps", []) or []:
                if not str(step.get("uses", "")).startswith("actions/checkout"):
                    continue
                persist = (step.get("with") or {}).get("persist-credentials")
                expected = (path.name, job_name) in credentialed_push_jobs
                assert persist is expected, f"{path.name}:{job_name}: persist-credentials must be {expected}"

    # The exempted docs push job legitimately persists credentials to push.
    docs_wf = _load("reusable-docs-pages.yml")
    push_checkout = next(
        s for s in docs_wf["jobs"]["push"]["steps"] if str(s.get("uses", "")).startswith("actions/checkout")
    )
    assert push_checkout["with"]["persist-credentials"] is True


@pytest.mark.parametrize(
    ("environment", "helper_result", "workflow_result"),
    [
        ({}, None, False),
        ({"protection_rules": []}, False, False),
        ({"protection_rules": [{"type": "required_reviewers"}]}, False, False),
        ({"protection_rules": [{"type": "required_reviewers", "reviewers": None}]}, False, False),
        ({"protection_rules": [{"type": "required_reviewers", "reviewers": []}]}, False, False),
        (
            {
                "protection_rules": [
                    {"type": "required_reviewers", "reviewers": [{"type": "User", "reviewer": {"id": 1}}]}
                ]
            },
            True,
            True,
        ),
    ],
)
def test_app_store_reviewer_gate_matches_github_helper_fixtures(
    monkeypatch: pytest.MonkeyPatch,
    environment: JsonDict,
    helper_result: bool | None,
    workflow_result: bool,
) -> None:
    from aviato import github as github_api

    monkeypatch.setattr(github_api, "gh_json_optional", lambda *_args, **_kwargs: environment)
    assert github_api.protected_environment_has_reviewers("owner/repo", "app-store-connect") is helper_result

    workflow = _load("reusable-app-store-connect.yml")
    probe = next(
        step
        for step in workflow["jobs"]["app-store-connect"]["steps"]
        if "requires reviewers" in str(step.get("name", ""))
    )
    match = re.search(r"jq -e '([^']+)'", probe["run"])
    assert match, "reviewer probe must use an inspectable jq predicate"
    completed = subprocess.run(
        ["jq", "-e", match.group(1)],
        input=json.dumps(environment),
        text=True,
        capture_output=True,
        check=False,
    )
    assert (completed.returncode == 0) is workflow_result


def test_app_store_receipt_is_persisted_by_isolated_release_evidence_job() -> None:
    workflow = _load("reusable-app-store-connect.yml")
    deploy = workflow["jobs"]["app-store-connect"]
    evidence = workflow["jobs"]["release-evidence"]

    assert deploy.get("permissions", {}).get("contents") != "write"
    assert evidence["needs"] == "app-store-connect"
    assert evidence["permissions"] == {"contents": "write"}

    encoded = json.dumps(evidence)
    assert "secrets." not in encoded
    assert "actions/checkout" not in encoded
    for consumer_command in ("xcodebuild", "pip install", "npm ", "eval "):
        assert consumer_command not in encoded

    steps = evidence["steps"]
    download = next(step for step in steps if "actions/download-artifact" in str(step.get("uses", "")))
    assert download["with"]["name"] == "app-store-connect-upload"
    persist = next(step for step in steps if "gh release upload" in str(step.get("run", "")))
    run = persist["run"]
    assert "--clobber" in run, "receipt asset persistence must be rerun-safe"
    assert "gh release edit" in run
    assert "<!-- aviato:app-store-connect-receipt:start -->" in run
    assert "<!-- aviato:app-store-connect-receipt:end -->" in run
    assert "$0 == start { replacing = 1" in run
    assert "$0 == end { replacing = 0" in run


def test_app_store_release_evidence_sets_explicit_repository_context() -> None:
    workflow = _load("reusable-app-store-connect.yml")
    evidence = workflow["jobs"]["release-evidence"]
    persist = next(step for step in evidence["steps"] if "gh release upload" in str(step.get("run", "")))

    assert persist["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert persist["env"]["GH_REPO"] == "${{ github.repository }}"


def test_app_store_receipt_asset_and_url_share_exact_basename() -> None:
    workflow = _load("reusable-app-store-connect.yml")
    evidence = workflow["jobs"]["release-evidence"]
    persist = next(step for step in evidence["steps"] if "gh release upload" in str(step.get("run", "")))
    run = persist["run"]

    assert persist["env"]["ASSET_NAME"] == "app-store-connect-upload.log"
    assert 'asset="receipt/${ASSET_NAME}"' in run
    assert 'cp "${downloaded_receipt}" "${asset}"' in run
    assert 'gh release upload "${RELEASE_TAG}" "${asset}" --clobber' in run
    assert "/${ASSET_NAME})" in run
    assert "#app-store-connect-upload.log" not in run


def test_docs_deploy_callers_do_not_grant_inert_actions_read() -> None:
    for caller in sorted(SCAFFOLD_FILES.glob("wf-docs-*.yml")):
        body = caller.read_text(encoding="utf-8")
        docs_job = body[body.index("\n  docs:") :]
        assert "      actions: read" not in docs_job, caller.name


def test_release_workflow_splits_derive_from_write_job() -> None:
    # C12-W1: the heavy derive phase (pip install + aviato over full history) must hold
    # NO write token; only the propose/tag job gets the writes (contents/pull-requests,
    # plus actions:write for the §5.9 release-branch check dispatch), and nothing is
    # granted at workflow level.
    wf = _load("reusable-release.yml")
    assert wf["permissions"] == {}, "reusable-release must grant nothing at workflow level"
    derive = wf["jobs"]["derive"]
    assert derive["permissions"] == {"contents": "read"}
    assert "GH_TOKEN" not in (derive.get("env") or {}), "derive must not receive the job token"
    checkout = next(s for s in derive["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"].get("persist-credentials") is False
    release = wf["jobs"]["release"]
    assert release["permissions"] == {"contents": "write", "pull-requests": "write", "actions": "write"}
    assert release["needs"] == "derive"
    assert "release == 'true'" in str(release.get("if", ""))


def test_common_lint_lints_every_dockerfile() -> None:
    # §14.1: common lint covers Dockerfiles where present; discovering many files
    # must not silently lint only the first one.
    body = (WORKFLOWS / "reusable-common-lint.yml").read_text(encoding="utf-8")
    assert 'for dockerfile in "${dockerfiles[@]}"' in body
    assert "${dockerfiles[0]}" not in body


def test_npm_workflows_harden_installs_before_installing() -> None:
    # npm min-release-age and ignore-scripts reduce dependency-confusion / postinstall
    # risk. npm 11+ is required because older npm rejects min-release-age.
    for name, job_name in (("reusable-node-ci.yml", "node-ci"),):
        wf = _load(name)
        on_block = _on(wf)
        assert on_block["workflow_call"]["inputs"]["node-version"]["default"] == "24"
        steps = wf["jobs"][job_name]["steps"]
        harden = next(s for s in steps if s.get("name") == "Harden npm install behavior")
        install = next(s for s in steps if s.get("name") == "Install")
        run = harden["run"]
        assert 'npm_version="$(npm --version)"' in run
        # finding 13: min-release-age is DEFINED from npm 11.10.0 (verified
        # empirically); the gate must check the minor, not just the major.
        assert '[[ "${npm_major}" =~ ^[0-9]+$ && "${npm_minor}" =~ ^[0-9]+$ ]]' in run
        assert '[ "${npm_major}" -lt 11 ]' in run
        assert '[ "${npm_minor}" -lt 10 ]' in run
        assert "::error::npm ${npm_version} does not support min-release-age" in run
        assert "exit 1" in run
        assert "npm config set ignore-scripts true --location=user" in run
        assert "npm config set engine-strict true --location=user" in run
        assert "NPM_CONFIG_IGNORE_SCRIPTS=true" in run
        assert "NPM_CONFIG_ENGINE_STRICT=true" in run
        assert "NPM_CONFIG_MIN_RELEASE_AGE=7" in run
        assert "npm config set min-release-age 7 --location=user" in run
        assert steps.index(harden) < steps.index(install), f"{name} must harden npm before install"

    # C12-W4/Zensical: the docs publish workflow was rewritten off npm entirely (pip/Zensical/
    # mike) — it must contain no `npm ` invocation at all, so npm can't sneak back in un-hardened.
    docs_body = (WORKFLOWS / "reusable-docs-pages.yml").read_text(encoding="utf-8")
    assert "npm " not in docs_body, "reusable-docs-pages.yml must not invoke npm (Zensical/mike, pip-only)"


def test_node_service_scaffold_uses_npm11_capable_node_default() -> None:
    body = (SCAFFOLD_FILES / "wf-node-service.yml").read_text(encoding="utf-8")
    assert 'node-version: "24"' in body
    assert 'node-version: "22"' not in body
    assert 'lint-command: "npx --no-install eslint ."' in body


def test_docs_publish_installs_pinned_toolchain_fail_closed() -> None:
    # The Zensical/mike rewrite replaced the Docusaurus npm install/lint with a pip
    # install of an exact-pinned requirements file (§11.3), which must fail closed
    # (not silently proceed unpinned) when the file is missing.
    wf = _load("reusable-docs-pages.yml")
    build = wf["jobs"]["build"]
    steps = build["steps"]
    install = next(s for s in steps if s.get("name") == "Install docs toolchain (exact pins, §11.3)")
    run = install["run"]
    assert "DOCS_REQUIREMENTS" in install.get("env", {})
    assert 'if [ ! -f "${DOCS_REQUIREMENTS}" ]' in run
    assert "::error::" in run
    assert "exit 1" in run
    assert 'python3 -m pip install --quiet -r "${DOCS_REQUIREMENTS}"' in run

    # C12-W4: consumer code runs under read-only scopes. configure-pages requires
    # pages:read; contents:write appears ONLY in the separate push job.
    assert build["permissions"] == {"contents": "read", "pages": "read"}
    emit = next(s for s in steps if s.get("name") == "Emit language API docs")
    assert steps.index(install) < steps.index(emit)
    assert wf["jobs"]["push"]["permissions"] == {"contents": "write"}


def test_docs_publish_fetches_existing_branch_authenticated_fail_closed() -> None:
    # Review finding: the old "fetch existing docs branch" line used an unauthenticated
    # ambient `git fetch origin ... || true`, which fails silently on private repos
    # (checkout uses persist-credentials: false) — mike then builds an orphan branch and
    # the push job's fast-forward check rejects it, breaking publishing permanently after
    # the first release. The fetch must be a separate, step-scoped-token, fail-closed step.
    wf = _load("reusable-docs-pages.yml")
    build = wf["jobs"]["build"]
    steps = build["steps"]
    fetch = next(s for s in steps if s.get("name") == "Fetch existing docs branch")
    run = fetch["run"]
    assert fetch.get("env", {}).get("GH_TOKEN") == "${{ github.token }}"
    assert "refusing to build an orphan docs branch" in run
    assert "git ls-remote --exit-code --heads" in run
    assert '"${status}" -eq 2' in run, "a missing branch (first deploy) must not fail closed"
    assert "|| true" not in run

    deploy = next(s for s in steps if s.get("name") == "Deploy version onto the local docs branch (mike)")
    assert "git fetch origin" not in deploy["run"], "the old unauthenticated ambient fetch must be removed"
    assert steps.index(fetch) < steps.index(deploy)

    # C12-W4: the job token stays step-scoped — it must not leak into the consumer eval
    # step or the mike deploy step's environment or command text.
    emit = next(s for s in steps if s.get("name") == "Emit language API docs")
    assert "GH_TOKEN" not in (emit.get("env") or {})
    assert "GH_TOKEN" not in emit.get("run", "")
    assert "GH_TOKEN" not in (deploy.get("env") or {})
    assert "GH_TOKEN" not in deploy["run"]


def test_docs_publish_refuses_default_branch_as_docs_branch() -> None:
    # Review finding (minor): docs-branch must never be the repository default branch —
    # mike's history-rewriting deploy onto the default branch would clobber it.
    wf = _load("reusable-docs-pages.yml")
    steps = wf["jobs"]["build"]["steps"]
    guard = next(s for s in steps if s.get("name") == "Refuse to target the default branch")
    run = guard["run"]
    assert guard.get("env", {}).get("DOCS_BRANCH") == "${{ inputs.docs-branch }}"
    assert guard.get("env", {}).get("DEFAULT_BRANCH") == "${{ github.event.repository.default_branch }}"
    assert '"${DOCS_BRANCH}" = "${DEFAULT_BRANCH}"' in run
    assert "::error::" in run
    assert "exit 1" in run
    deploy = next(s for s in steps if s.get("name") == "Deploy version onto the local docs branch (mike)")
    assert steps.index(guard) < steps.index(deploy)


def test_common_lint_blocks_unsafe_npx_registry_fetches() -> None:
    # The npx gate runs as ONE implementation inside `aviato lint-actions` (no in-workflow
    # grep mirror to drift — R9-5); common lint must invoke it via the supply-chain step.
    wf = _load("reusable-common-lint.yml")
    steps = wf["jobs"]["common-lint"]["steps"]
    pins = next(s for s in steps if s.get("name") == "Supply-chain pins (blocking)")
    assert "aviato lint-actions ." in pins["run"]
    from aviato.plugins.actionpins import unpinned_tool_invocations

    assert unpinned_tool_invocations("          npx eslint .\n") == [
        "npx may fetch an unpinned registry tool: npx eslint ."
    ]
    assert unpinned_tool_invocations("          npx --no-install eslint .\n") == []


def test_app_store_connect_secrets_are_step_scoped() -> None:
    # §11.2: App Store credentials must not be job-wide, and caller-controlled version
    # commands must run before signing assets are installed and without Apple secrets.
    wf = _load("reusable-app-store-connect.yml")
    job = wf["jobs"]["app-store-connect"]
    job_env = str(job.get("env", {}))
    for name in (
        "APP_STORE_CONNECT_ISSUER_ID",
        "APP_STORE_CONNECT_KEY_ID",
        "APP_STORE_CONNECT_API_PRIVATE_KEY",
        "APPLE_CERTIFICATE_P12_BASE64",
        "APPLE_CERTIFICATE_PASSWORD",
        "APPLE_PROVISIONING_PROFILE_BASE64",
    ):
        assert name not in job_env, f"{name} must not be job-wide"

    steps = job["steps"]
    version = next(s for s in steps if s.get("name") == "Apply version command")
    signing = next(s for s in steps if s.get("name") == "Install signing assets")
    upload = next(s for s in steps if s.get("name") == "Upload to App Store Connect")
    assert steps.index(version) < steps.index(signing), "version command must run before signing assets are installed"
    assert "APP_STORE_CONNECT" not in str(version.get("env", {}))
    assert "APPLE_" not in str(version.get("env", {}))
    assert "APP_STORE_CONNECT_API_PRIVATE_KEY" in signing.get("env", {})
    assert "APPLE_CERTIFICATE_P12_BASE64" in signing.get("env", {})
    assert "APPLE_PROVISIONING_PROFILE_BASE64" in signing.get("env", {})
    assert "APP_STORE_CONNECT_ISSUER_ID" in upload.get("env", {})
    assert "APP_STORE_CONNECT_KEY_ID" in upload.get("env", {})
    assert "APP_STORE_CONNECT_API_PRIVATE_KEY" not in upload.get("env", {})

    # C12-W6: only the BOUNDED built-in submit may hold the ASC private key; the custom
    # eval gets identifiers only and runs AFTER the signing cleanup (no on-disk .p8).
    builtin = next(s for s in steps if s.get("name") == "Submit for review (built-in)")
    custom = next(s for s in steps if s.get("name") == "Submit for review (custom command)")
    cleanup = next(s for s in steps if s.get("name") == "Cleanup signing assets")
    assert "APP_STORE_CONNECT_API_PRIVATE_KEY" in builtin.get("env", {})
    assert "eval" not in str(builtin.get("run", "")), "the built-in submit must not eval operator input"
    assert "APP_STORE_CONNECT_API_PRIVATE_KEY" not in custom.get("env", {})
    assert steps.index(cleanup) < steps.index(custom), "custom submit must run after signing cleanup"

    # §11.4: the environment reviewer probe must run before any secret materializes.
    probe = next(s for s in steps if "requires reviewers" in str(s.get("name", "")))
    assert steps.index(probe) < steps.index(signing)
    assert "required_reviewers" in str(probe.get("run", ""))


def test_security_baseline_jitters_scheduled_scans_at_the_chokepoint() -> None:
    # §5.14/§5.5: SAST/secret/dependency scans run on a JITTERED schedule so a fleet on the
    # same weekly cron does not stampede the platform. The jitter must (a) live on the
    # privilege-probe job — the single chokepoint every scan job `needs:` — so delaying it
    # defers the whole baseline, and (b) be gated to schedule events only, so PR and
    # release-ref runs stay immediate (no latency on the deploy gate / PR feedback).
    wf = _load("reusable-security-baseline.yml")
    jobs = wf["jobs"]

    # (a) every scan job funnels through privilege-probe — the chokepoint the jitter relies on.
    for scan_job in ("codeql", "dependency-review", "dependency-scan", "secret-scan"):
        needs = jobs[scan_job].get("needs")
        message = f"{scan_job} must `needs: privilege-probe` so the jitter on that job defers it"
        assert "privilege-probe" in needs, message

    # (b) privilege-probe has a schedule-gated RANDOM sleep before it does any work.
    probe_steps = jobs["privilege-probe"]["steps"]
    jitter = next(
        (s for s in probe_steps if "sleep" in s.get("run", "") and "RANDOM" in s.get("run", "")),
        None,
    )
    assert jitter is not None, "privilege-probe has no anti-stampede jitter step"
    assert "schedule" in jitter.get("if", ""), "jitter must be gated to schedule events (no PR/release-ref latency)"
    # jitter must run BEFORE the privilege check, or downstream scans aren't actually deferred.
    assert probe_steps.index(jitter) < next(
        i
        for i, s in enumerate(probe_steps)
        if "security-events" in s.get("name", "").lower() or "scope" in s.get("name", "").lower()
    ), "jitter must precede the privilege-probe work step"


def test_release_tag_phase_proves_version_source_was_bumped() -> None:
    # §5.9/§719: the tag phase must PROVE the merged commit actually bumped the version-
    # source to NEXT before tagging — a commit whose subject merely claims `chore(release):
    # NEXT` but never bumped the manifest must not be tagged/deployed. The proof re-runs the
    # idempotent bump and fails if it produces any change. Guard it structurally (the live
    # gate is operator-verified; nothing else catches a regression here).
    wf = _load("reusable-release.yml")
    tag_step = next(
        s
        for j in wf["jobs"].values()
        if isinstance(j, dict)
        for s in j.get("steps", [])
        if isinstance(s, dict) and s.get("id") == "tag"
    )
    run = tag_step["run"]
    assert "aviato bump-version" in run, "tag phase must re-run the bump to verify it"
    assert "git diff" in run, "tag phase must detect an un-bumped manifest via git diff"
    # The verification must come BEFORE the actual `git tag`.
    assert run.index("aviato bump-version") < run.index("git tag"), "verify the bump before tagging"


def test_security_baseline_retains_fail_closed_structure() -> None:
    # §5.14/§8.16: the security baseline must (a) probe the findings-upload privilege and
    # hard-fail without it, (b) run each scan only after that probe, (c) emit a per-run
    # heartbeat even on zero findings, and (d) gate on required scans. This is the one
    # place a refactor could silently remove the fail-closed posture; the live gate is
    # operator-verified, so guard the protective structure statically.
    wf = _load("reusable-security-baseline.yml")
    jobs = wf["jobs"]

    assert "privilege-probe" in jobs, "missing runtime findings-upload privilege probe"
    assert "heartbeat" in jobs, "missing per-run heartbeat job"

    scan_jobs = ["codeql", "dependency-review", "dependency-scan", "secret-scan"]
    for name in scan_jobs:
        assert name in jobs, f"missing scan job {name}"
        assert "privilege-probe" in jobs[name].get("needs", []), f"{name} must run after the privilege probe"

    heartbeat_needs = jobs["heartbeat"].get("needs", [])
    for name in scan_jobs:
        assert name in heartbeat_needs, f"heartbeat must depend on {name} so a skipped scan is detectable"

    gate_steps = [step.get("name", "") for step in jobs["heartbeat"].get("steps", []) if isinstance(step, dict)]
    assert any("Gate" in name for name in gate_steps), "missing 'Gate on required scans' step"


def _codeql_severity_gate() -> tuple[JsonDict, JsonDict]:
    wf = _load("reusable-security-baseline.yml")
    job = wf["jobs"]["codeql"]
    step = next(s for s in job["steps"] if s.get("name") == "Gate CodeQL high/critical alerts")
    return job, step


def test_codeql_severity_gate_runs_after_processed_analysis_and_before_heartbeat() -> None:
    job, gate = _codeql_severity_gate()
    analyze_index = next(
        i for i, step in enumerate(job["steps"]) if step.get("uses") == "github/codeql-action/analyze@v4"
    )
    gate_index = job["steps"].index(gate)

    assert job["steps"][analyze_index]["with"]["wait-for-processing"] is True
    assert analyze_index < gate_index
    assert gate["env"]["ANALYZED_REF"] == "${{ needs.resolve-target.outputs.canonical-ref }}"
    assert gate["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert all("GH_TOKEN" not in step.get("env", {}) for step in job["steps"] if step is not gate)

    run = gate["run"]
    assert "--paginate" in run and "--slurp" in run
    assert "state=open" in run and "tool_name=CodeQL" in run and "ref=" in run
    assert "security_severity_level" in run
    assert 'alert.get("number")' in run and "most_recent_instance" not in run

    heartbeat = _load("reusable-security-baseline.yml")["jobs"]["heartbeat"]
    assert "codeql" in heartbeat["needs"]


@pytest.mark.parametrize(
    ("pages", "expected_returncode"),
    [
        ([[]], 0),
        (
            [[{"number": 1, "rule": {"id": "medium", "security_severity_level": "medium"}, "html_url": "https://e/1"}]],
            0,
        ),
        (
            [
                [
                    {
                        "number": 5,
                        "rule": {"id": "non-security", "security_severity_level": None},
                        "html_url": "https://e/5",
                    }
                ]
            ],
            0,
        ),
        ([[{"number": 2, "rule": {"id": "high", "security_severity_level": "high"}, "html_url": "https://e/2"}]], 1),
        (
            [
                [
                    {
                        "number": 3,
                        "rule": {"id": "critical", "security_severity_level": "critical"},
                        "html_url": "https://e/3",
                    }
                ]
            ],
            1,
        ),
        (
            [
                [],
                [{"number": 4, "rule": {"id": "later", "security_severity_level": "high"}, "html_url": "https://e/4"}],
            ],
            1,
        ),
    ],
)
def test_codeql_severity_gate_deterministic_alert_fixtures(
    tmp_path: Path, pages: list[list[JsonDict]], expected_returncode: int
) -> None:
    """Exercise the operative gate with deterministic alert pages (the local SARIF canary)."""
    _, gate = _codeql_severity_gate()
    fake_gh = tmp_path / "gh"
    fake_gh.write_text('#!/bin/sh\nprintf "%s\\n" "$GH_RESPONSE"\n', encoding="utf-8")
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GH_RESPONSE": json.dumps(pages),
        "GH_TOKEN": "fixture-token",
        "GITHUB_REPOSITORY": "o/r",
        "ANALYZED_REF": "refs/heads/canary",
    }
    result = subprocess.run(["bash", "-c", gate["run"]], env=env, text=True, capture_output=True, check=False)
    assert result.returncode == expected_returncode, result.stdout + result.stderr
    assert "fixture-token" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("response", "exit_code"),
    [
        ("not-json", 0),
        ("[]", 0),
        ("", 1),
        (json.dumps([[{"number": 6, "rule": {"id": "missing"}, "html_url": "https://e/6"}]]), 0),
        (
            json.dumps(
                [
                    [
                        {
                            "number": "7",
                            "rule": {"id": "unsafe\nrule", "security_severity_level": "high"},
                            "html_url": "javascript:x",
                        }
                    ]
                ]
            ),
            0,
        ),
    ],
)
def test_codeql_severity_gate_fails_closed_on_api_or_response_ambiguity(
    tmp_path: Path, response: str, exit_code: int
) -> None:
    _, gate = _codeql_severity_gate()
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$GH_RESPONSE"\nexit "$GH_EXIT"\n',
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GH_RESPONSE": response,
        "GH_EXIT": str(exit_code),
        "GH_TOKEN": "fixture-token",
        "GITHUB_REPOSITORY": "o/r",
        "ANALYZED_REF": "refs/heads/canary",
    }
    result = subprocess.run(["bash", "-c", gate["run"]], env=env, text=True, capture_output=True, check=False)
    assert result.returncode != 0, result.stdout + result.stderr


def test_security_ref_and_sarif_evidence_share_one_resolved_target() -> None:
    """Every source read and findings upload must bind to the same immutable commit."""
    wf = _load("reusable-security-baseline.yml")
    on_block = _on(wf)
    inputs = on_block["workflow_call"]["inputs"]
    assert inputs["ref"]["required"] is False
    assert inputs["sha"]["required"] is False

    jobs = wf["jobs"]
    resolver = jobs["resolve-target"]
    assert resolver["outputs"] == {
        "canonical-ref": "${{ steps.canonicalize.outputs.canonical-ref }}",
        "analyzed-sha": "${{ steps.resolve.outputs.analyzed-sha }}",
    }
    steps = resolver["steps"]
    canonicalize_index = next(i for i, step in enumerate(steps) if step.get("id") == "canonicalize")
    # Match any checkout major: this guard is about ref/SHA binding, and a
    # hardcoded pin turns every checkout version bump into a spurious failure.
    checkout_index = next(
        i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert canonicalize_index < checkout_index, "bare tags must be canonicalized before checkout resolves them"
    canonicalize_script = steps[canonicalize_index]["run"]
    assert 'canonical_ref="refs/tags/${REQUESTED_REF}"' in canonicalize_script
    assert steps[checkout_index]["with"]["ref"] == "${{ steps.canonicalize.outputs.canonical-ref }}"
    resolve_script = next(step["run"] for step in resolver["steps"] if step.get("id") == "resolve")
    assert "^{commit}" in resolve_script
    assert "inputs.sha" in str(resolver["steps"])

    canonical_ref = "${{ needs.resolve-target.outputs.canonical-ref }}"
    analyzed_sha = "${{ needs.resolve-target.outputs.analyzed-sha }}"
    for job_name in ("codeql", "dependency-review", "dependency-scan", "secret-scan"):
        checkout = next(
            step for step in jobs[job_name]["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")
        )
        assert checkout["with"]["ref"] == analyzed_sha, job_name

    analyze = next(step for step in jobs["codeql"]["steps"] if step.get("uses") == "github/codeql-action/analyze@v4")
    assert analyze["with"]["ref"] == canonical_ref
    assert analyze["with"]["sha"] == analyzed_sha

    uploads = [
        step
        for job_name in ("dependency-scan", "secret-scan")
        for step in jobs[job_name]["steps"]
        if step.get("uses") == "github/codeql-action/upload-sarif@v4"
    ]
    assert len(uploads) == 2
    for upload in uploads:
        assert upload["with"]["ref"] == canonical_ref
        assert upload["with"]["sha"] == analyzed_sha

    heartbeat = jobs["heartbeat"]
    assert "resolve-target" in heartbeat["needs"]
    upload = next(step for step in heartbeat["steps"] if step.get("uses") == "actions/upload-artifact@v7")
    assert upload["with"]["name"] == "aviato-security-heartbeat-${{ needs.resolve-target.outputs.analyzed-sha }}"


def test_docs_security_ref_uses_full_tag_and_release_gate_sha() -> None:
    """Out-of-band docs scans must use the exact target already accepted by the release gate."""
    for caller in sorted(SCAFFOLD_FILES.glob("wf-docs-*.yml")):
        body = caller.read_text(encoding="utf-8")
        security_block = body[body.index("\n  security:") : body.index("\n  docs:")]
        assert "needs: [resolve, release-gate]" in security_block, caller.name
        assert "ref: refs/tags/${{ needs.resolve.outputs.tag }}" in security_block, caller.name
        assert "sha: ${{ needs.release-gate.outputs.gated-sha }}" in security_block, caller.name


def test_aviato_ref_pin_guard_present_and_regex_correct() -> None:
    # R2-5-F2 / R4-6: a fail-closed supply-chain control — the release/automation workflows must
    # refuse to install the Library off an unpinned/branch ref. Assert (a) the guard step exists in
    # both workflows BEFORE the `pip install …@${AVIATO_REF}` step, and (b) extract the embedded ERE
    # and exercise it over a battery, so a refactor dropping the guard or loosening the regex (e.g.
    # accidentally accepting `@main`) goes red. (Mirrors the monotonic-alias parity approach.)
    import re

    guard_re = re.compile(r"AVIATO_REF.*?=~\s+(\S+)\s+\]\]")
    for name in (
        "reusable-release.yml",
        "reusable-common-lint.yml",
    ):
        body = (WORKFLOWS / name).read_text()
        m = guard_re.search(body)
        assert m, f"{name} missing the AVIATO_REF pin guard"
        # The guard must run BEFORE the pinned install.
        assert body.index("AVIATO_REF") < body.index(
            'pip install "git+https://github.com/mattas-net/aviato@${AVIATO_REF}"'
        )
        pattern = re.compile(m.group(1))
        for good in ("1.2.3", "1.2.3-alpha1", "1.2.3-beta2", "7", "1.10.0"):
            assert pattern.fullmatch(good), f"{name}: should accept {good}"
        for bad in (
            "",
            "main",
            "v1.2.3",
            "release/x",
            "1.2",
            "1.2.3-rc1",
            "1.2.3-beta.1",
        ):
            assert not pattern.fullmatch(bad), f"{name}: should reject {bad!r}"


def test_ghcr_image_name_is_lowercased() -> None:
    # R3-2-GHCRCASE/R3-5-E: GHCR/OCI repo paths must be lowercase; github.repository preserves case,
    # so the "Determine image name" step must lowercase before building the ghcr.io/<image> ref.
    body = (WORKFLOWS / "reusable-docker-ghcr.yml").read_text()
    assert "tr '[:upper:]' '[:lower:]'" in body or "${image,,}" in body, "GHCR image name not lowercased"


def test_pypi_publish_isolates_build_from_oidc_token() -> None:
    # R3-2-PYPIJOB: the operator build/install commands (eval) must run in an UNPRIVILEGED job; only a
    # separate publish job (which runs no eval) may hold id-token/attestations. This keeps a
    # compromised build dependency away from the OIDC token (trusted-publishing isolation).
    # R4-5-B: compute EFFECTIVE permissions — a job inherits the TOP-LEVEL block when it omits its
    # own, so checking only the job-level key would pass even if the build job dropped its downgrade
    # and inherited the token. The eval-bearing job must EXPLICITLY exclude the publish token.
    import json as _json

    wf = _load("reusable-pypi-publish.yml")
    top_perms = wf.get("permissions", {}) or {}
    jobs = wf["jobs"]
    caller_jobs = _rendered_python_library_workflow()["jobs"]

    def holds_token(perms: JsonDict) -> bool:
        return perms.get("id-token") == "write" or perms.get("attestations") == "write"

    for job_name, job in jobs.items():
        job_perms = job.get("permissions")
        # Effective perms: a job WITHOUT its own `permissions:` inherits the top-level block.
        effective = job_perms if job_perms is not None else top_perms
        runs_eval = "eval " in _json.dumps(job.get("steps", []))
        message = f"job {job_name!r} runs build code with effective access to the OIDC/attestation token"
        assert not (holds_token(effective) and runs_eval), message

    # The build (eval) job must declare its OWN permissions that exclude the token (not merely rely
    # on the absence of a job-level key, which would inherit the top-level token).
    build_perms = jobs["build"].get("permissions")
    message = "build job must explicitly downgrade permissions to exclude id-token/attestations"
    assert build_perms is not None and not holds_token(build_perms), message
    # The privileged publish job is consumer-local, depends on the reusable builder,
    # and runs no operator-selected build command.
    publisher = caller_jobs["pypi-publish"]
    assert "pypi" in publisher["needs"]
    assert holds_token(publisher["permissions"])
    assert "eval " not in _json.dumps(publisher.get("steps", [])), "publish job must run no build code"


def test_pypi_artifact_upload_download_paths_are_symmetric() -> None:
    # R4-5-D: the build job uploads the dist+sbom and the publish job downloads them; the paths must
    # reconstruct symmetrically so the attest subject-path / pypi packages-dir (which read
    # `<working-directory>/<packages-dir>`) resolve to the actual files. upload-artifact roots the
    # artifact at the least-common-ancestor of its `path:` entries; downloading to `path: <wd>`
    # re-roots there. The round-trip is exact IFF every uploaded path is under `<wd>` and download
    # extracts to exactly `<wd>` (a wrong download path would yield `<wd>/<wd>/...` or a missing dir).
    wf = _load("reusable-pypi-publish.yml")
    caller = _rendered_python_library_workflow()
    steps = {"build": wf["jobs"]["build"]["steps"], "publish": caller["jobs"]["pypi-publish"]["steps"]}

    def _step(job: str, action_substr: str) -> JsonDict:
        return next(s for s in steps[job] if action_substr in (s.get("uses") or ""))

    up = _step("build", "upload-artifact")["with"]
    down = _step("publish", "download-artifact")["with"]
    wd = "${{ inputs.working-directory }}"

    on_block = _on(wf)
    assert on_block["workflow_call"]["outputs"]["artifact-name"]["value"] == "${{ jobs.build.outputs.artifact-name }}"
    assert up["name"] == "aviato-pypi-dist"
    assert down["name"] == "${{ needs.pypi.outputs.artifact-name }}"
    # Every uploaded path is under <wd> (so the least-common-ancestor is <wd>).
    upload_paths = [p for p in str(up["path"]).splitlines() if p.strip()]
    assert upload_paths, "upload step lists no paths"
    for p in upload_paths:
        assert p.strip().startswith(f"{wd}/"), f"upload path not under working-directory: {p!r}"
    # The caller passes working-directory ".", so extraction at its root reconstructs dist/ + SBOM.
    assert down["path"] == "."


def test_pypi_audit_scope_is_exactly_the_wheel_dependency_closure() -> None:
    # Two live publish failures proved environment-mode auditing gates the publish on things
    # that never ship: (0.2.0) the project ITSELF — absent from PyPI on a first publish, its
    # "could not be audited" skip is fatal under --strict, so a first publish could never pass
    # its own gate; (0.2.1) the venv's runner-seeded pip 25.0.1 (PYSEC-2026-196 et al.) — venv
    # tooling, not a project dependency. The audit must scan a frozen requirements set from a
    # DEDICATED project venv (freeze omits pip/setuptools/wheel tooling; the project's own
    # distribution is --exclude'd by name), audited by a scanner living in a SEPARATE venv so
    # pip-audit's own dependencies are never co-audited or co-resolved with the project's.
    wf = _load("reusable-pypi-publish.yml")
    steps = wf["jobs"]["build"]["steps"]
    scan = next(s for s in steps if s.get("name") == "Dependency vulnerability scan (gate)")
    run = scan["run"]
    assert "python -m venv /tmp/audit-venv" in run, "scanner venv missing"
    assert "python -m venv /tmp/project-venv" in run, "dedicated project venv missing"
    assert '/tmp/project-venv/bin/python -m pip install --quiet "${PACKAGES_DIR}"/*.whl' in run
    assert '/tmp/audit-venv/bin/python -m pip install --quiet "pip-audit==' in run
    assert "pip freeze" in run and "--exclude" in run, "audited set must be the frozen closure minus the project"
    audit_line = next(line for line in run.splitlines() if "-m pip_audit" in line)
    assert "/tmp/audit-venv/bin/python -m pip_audit" in audit_line, "audit must run from the scanner venv"
    for flag in ("--strict", "--no-deps", "-r "):
        assert flag in audit_line, f"pip_audit must run with {flag.strip()}"
    assert run.index("pip freeze") < run.index("-m pip_audit"), "freeze must precede the audit"


def test_release_propose_dispatches_ci_on_release_branch() -> None:
    # §5.9: a GITHUB_TOKEN-pushed release branch never triggers workflows (event
    # suppression), so required status checks could never report on the release PR —
    # and under a required_status_checks ruleset (no bypass actors, §settings) that
    # makes release PRs permanently unmergeable by ANYONE, wedging the release flow.
    # workflow_dispatch is exempt from the suppression: the propose phase must
    # dispatch the caller workflow at the release branch so the release PR reports
    # the same check contexts a human branch would.
    body = (WORKFLOWS / "reusable-release.yml").read_text()
    dispatch_cmd = 'gh workflow run "${workflow_path##*/}" --ref "${branch}"'
    assert dispatch_cmd in body, "propose phase must dispatch the caller workflow on the release branch"
    wf = _load("reusable-release.yml")
    perms = wf["jobs"]["release"]["permissions"]
    assert perms.get("actions") == "write", "release job needs actions: write to dispatch the caller"


def test_ci_callers_enable_release_pr_check_dispatch() -> None:
    # Companion to the propose-phase dispatch: `gh workflow run` fails unless the
    # caller declares the workflow_dispatch trigger, and a caller cannot grant a
    # called workflow more than its own ceiling — so every CI caller that composes
    # the release pipeline must carry both the trigger and `actions: write`.
    ci_callers = [
        p for p in sorted(SCAFFOLD_FILES.glob("wf-*.yml")) if "reusable-release.yml" in p.read_text(encoding="utf-8")
    ]
    assert ci_callers, "no CI caller bodies compose reusable-release.yml?"
    for caller in ci_callers:
        body = caller.read_text(encoding="utf-8")
        assert "workflow_dispatch:" in body, f"{caller.name}: release-branch check dispatch needs the trigger"
        assert "actions: write" in body, f"{caller.name}: caller ceiling must cover the release job's actions: write"


def test_ci_callers_publish_dispatch_status_bridge_from_resolved_pipeline_contexts() -> None:
    """Dispatch verification must report the profile's real required contexts on the PR SHA."""
    registry = Registry(MODULE_SOURCE_ROOT)
    for profile, variables in _TEMPLATE_EXAMPLE_VARS.items():
        workflow_body = next(
            artifact.body
            for artifact in resolved_artifacts(registry, profile, variables, pin="EXAMPLE_PIN", docs=False)
            if artifact.output == ".github/workflows/aviato-ci.yml"
        )
        workflow = yaml.safe_load(workflow_body)
        bridge = workflow["jobs"]["status-bridge"]

        resolved = resolve_profile(registry, profile)
        expected_contexts = {
            module.status_check for module in resolved.pipeline_modules if module.status_check is not None
        }
        steps = bridge["steps"]
        actual_contexts = {step["env"]["STATUS_CONTEXT"] for step in steps}

        assert bridge["if"] == "${{ always() && github.event_name == 'workflow_dispatch' }}", profile
        assert set(bridge["needs"]) == {"ci", "security", "common-lint"}, profile
        assert bridge["runs-on"] == "ubuntu-latest", profile
        assert bridge["permissions"] == {"statuses": "write"}, profile
        assert bridge["env"] == {"GH_TOKEN": "${{ github.token }}"}, profile
        assert actual_contexts == expected_contexts, profile
        assert len(steps) == len(expected_contexts), profile
        for step in steps:
            assert "uses" not in step, f"{profile}: status bridge must not check out or install code"
            assert step["env"]["STATUS_STATE"].endswith("&& 'success' || 'failure' }}")
            run = step["run"]
            assert "gh api" in run and "statuses/${GITHUB_SHA}" in run
            assert '-f state="${STATUS_STATE}"' in run
            assert '-f context="${STATUS_CONTEXT}"' in run
            assert "checkout" not in run.lower() and "install" not in run.lower()


def test_release_propose_tolerates_preseeded_version_source() -> None:
    # §5.9 bootstrap: on a repo whose version-source already equals NEXT (seeded at
    # onboard time, before the first release existed), the propose-phase bump is a
    # no-op — the release PR must still materialize via an empty marker commit instead
    # of dying on `git commit -am` with nothing staged. The TAG phase keys on the
    # commit subject and independently re-proves the manifest equals NEXT, so an empty
    # marker commit cannot tag a version the manifest doesn't carry.
    body = (WORKFLOWS / "reusable-release.yml").read_text()
    assert "if git diff --quiet; then" in body, "propose phase must detect the no-op bump"
    marker_commit = 'git commit --allow-empty -m "chore(release): ${NEXT}"'
    assert marker_commit in body, "propose must fall back to an empty marker commit on a pre-seeded version-source"


def test_release_phase_detector_accepts_squash_merge_subject() -> None:
    # R6-4-SQUASH: GitHub's DEFAULT squash-merge title format appends ' (#N)' (the PR number) to
    # the PR title, so the merged subject is `chore(release): NEXT (#42)`. The phase-detector regex
    # MUST accept that form — a bare end-anchor would miss it and the workflow would silently fall
    # through to the propose phase, refusing to tag any release on a repo using the default merge
    # mode. Extract the regex literal and exercise both subject formats.
    import re

    # R7-4-SQUASH-TAUT: exercise the regex actually present in the workflow, not a hand-written
    # copy. Extract the literal from `grep -Eq "<regex>"`, substitute the bash ${NEXT} interpolation
    # with a concrete version, and translate the bash end-anchor `\$` into a Python `$`. A future
    # workflow regex regression must make this test fail.
    body = (WORKFLOWS / "reusable-release.yml").read_text()
    match = re.search(r'grep -Eq "(\^chore[^"]+)"', body)
    assert match, "is_release_commit grep -Eq regex not found in reusable-release.yml"
    workflow_regex = match.group(1).replace("${NEXT}", re.escape("1.2.3")).replace(r"\$", "$")
    pattern = re.compile(workflow_regex)
    for accepted in (
        "chore(release): 1.2.3",
        "chore(release): 1.2.3 (#42)",
        "chore(release): 1.2.3 (#1234)",
    ):
        assert pattern.match(accepted), f"phase detector must accept: {accepted!r}"
    for rejected in (
        "chore(release): 1.2.4 (#42)",
        "chore: 1.2.3",
        "chore(release): 1.2.3-extra",
    ):
        assert not pattern.match(rejected), f"phase detector must NOT accept: {rejected!r}"


def test_app_store_secrets_not_exposed_to_operator_eval_steps() -> None:
    # R7-4-APPSTORE-OIDC: the 6 Apple/App-Store-Connect secrets must NOT live at JOB level (where
    # every step inherits them, including the operator-controlled `eval "$VERSION_COMMAND"` and
    # `eval "$SUBMIT_FOR_REVIEW_COMMAND"`). Each secret is scoped per-step to ONLY the step that
    # legitimately consumes it. The version-command step (which has no business with signing keys)
    # must NOT receive any of them; the submit-for-review-command step (which calls App Store
    # Connect) gets the API credentials only, NOT the certificate material.
    import json as _json

    wf = _load("reusable-app-store-connect.yml")
    job = wf["jobs"]["deploy"] if "deploy" in wf["jobs"] else next(iter(wf["jobs"].values()))
    secret_keys = {
        "APP_STORE_CONNECT_ISSUER_ID",
        "APP_STORE_CONNECT_KEY_ID",
        "APP_STORE_CONNECT_API_PRIVATE_KEY",
        "APPLE_CERTIFICATE_P12_BASE64",
        "APPLE_CERTIFICATE_PASSWORD",
        "APPLE_PROVISIONING_PROFILE_BASE64",
    }
    # Job-level env must NOT carry any Apple/ASC secret.
    job_env = job.get("env") or {}
    leaked = secret_keys & set(job_env)
    assert not leaked, f"job-level env still carries secrets that every step inherits: {sorted(leaked)}"

    # The operator `eval` steps must NOT have any of these secrets in their per-step env.
    eval_steps = [s for s in job["steps"] if "eval " in _json.dumps(s.get("run", ""))]
    assert eval_steps, "no operator eval steps found (workflow shape changed unexpectedly)"
    for step in eval_steps:
        step_env = step.get("env") or {}
        # C12-W6: NO eval step may see the certificate/provisioning material OR the ASC
        # API private key — the only key consumers are the signing install and the
        # bounded built-in submit (neither is an eval).
        forbidden = {
            "APPLE_CERTIFICATE_P12_BASE64",
            "APPLE_CERTIFICATE_PASSWORD",
            "APPLE_PROVISIONING_PROFILE_BASE64",
            "APP_STORE_CONNECT_API_PRIVATE_KEY",
        }
        leak = forbidden & set(step_env)
        assert not leak, f"eval step {step.get('name')!r} sees secret material: {sorted(leak)}"
        if "VERSION_COMMAND" in _json.dumps(step.get("env") or {}):
            # The version-command step has no legitimate need for ANY of the secrets.
            version_leak = secret_keys & set(step_env)
            assert not version_leak, f"version-command step sees secrets: {sorted(version_leak)}"


def test_common_lint_runs_aviato_lint_actions_not_grep() -> None:
    wf = (WORKFLOWS / "reusable-common-lint.yml").read_text(encoding="utf-8")
    assert "aviato lint-actions" in wf, "common-lint must run the single aviato lint-actions impl"
    assert "interps=" not in wf, "the grep mirror must be gone (parity flap removed)"
    assert "docker[[:space:]]+(run|pull)" not in wf, "the docker grep extractor must be gone"
