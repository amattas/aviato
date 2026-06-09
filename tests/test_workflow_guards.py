from __future__ import annotations

import yaml

from aviato.paths import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCAFFOLD_FILES = REPO_ROOT / "aviato" / "library" / "scaffold" / "files"


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def test_serializing_workflows_declare_per_repo_concurrency() -> None:
    # review #4/#26: the scheduled drift run, the release run, and the deploy publishes must
    # SERIALIZE per repo (queue, never cancel) so concurrent runs can't race a force-push / alias
    # move / duplicate publish. Guard the concurrency block structurally.
    for name in (
        "reusable-consumer-automation.yml",
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


def test_consumer_automation_jitters_scheduled_runs() -> None:
    # §5.5/§8.x: the scheduled drift/report caller MUST jitter before doing work so a
    # fleet sharing one cron does not stampede the hosting platform. Guard the jitter
    # step structurally so a refactor cannot silently drop it (it is otherwise only
    # exercised by a live scheduled run, which the test suite does not perform).
    wf = _load("reusable-consumer-automation.yml")
    runs = [
        step.get("run", "")
        for job in wf["jobs"].values()
        if isinstance(job, dict)
        for step in job.get("steps", [])
        if isinstance(step, dict)
    ]
    assert any("sleep" in run and "RANDOM" in run for run in runs), "no anti-stampede jitter step found"


def test_local_install_is_limited_to_structural_library_bootstrap() -> None:
    # §5.10: local-install is only for the Library bootstrapping itself before a
    # released ref exists. A consumer hand-editing local-install:true must fail before
    # `pip install -e .` unless the checkout has the Library anchors and bootstrap:true.
    for name, job_name in (
        # C12-W1: BOTH release jobs install Aviato; each must carry the full guard.
        ("reusable-release.yml", "derive"),
        ("reusable-release.yml", "release"),
        ("reusable-consumer-automation.yml", "drift-report"),
    ):
        wf = _load(name)
        install = next(s for s in wf["jobs"][job_name]["steps"] if s.get("name") == "Install Aviato (pinned)")
        run = install["run"]
        for anchor in (
            "aviato/core/__init__.py",
            "aviato/library/bundles",
            "aviato/library/scaffold",
            "aviato/library/policy.yml",
            ".github/aviato.yaml",
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
    gate_on = gate.get("on") or gate.get(True)
    assert "gated-sha" in (gate_on["workflow_call"].get("outputs") or {}), "gate must export gated-sha"
    for name in _DEPLOY_WORKFLOWS:
        wf = _load(name)
        on_block = wf.get("on") or wf.get(True)
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
        assert "gated-sha: ${{ needs.release-gate.outputs.gated-sha }}" in body, (
            f"{caller.name} wires a deploy without threading the gated SHA (C12-W2)"
        )


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
        on_block = wf.get("on") or wf.get(True)
        inputs = set(on_block["workflow_call"]["inputs"])
        missing = expected - inputs
        assert not missing, f"{name} missing shared-contract inputs: {sorted(missing)}"


def test_node_ci_gates_fail_loud_without_if_present() -> None:
    # finding 29: a consumer deleting the lint/test script from the operator-owned
    # manifest must FAIL the verify gate, not silently skip it.
    wf = _load("reusable-node-ci.yml")
    on_block = wf.get("on") or wf.get(True)
    inputs = on_block["workflow_call"]["inputs"]
    assert inputs["lint-command"]["default"] == "npm run lint"
    assert inputs["test-command"]["default"] == "npm test"


def test_docs_retention_defaults_to_keep_all() -> None:
    # finding 37 (operator decision): every released version's docs are kept; the
    # pruner must special-case cap<=0 — versions[:0] would otherwise prune EVERYTHING.
    wf = _load("reusable-docs-pages.yml")
    on_block = wf.get("on") or wf.get(True)
    assert on_block["workflow_call"]["inputs"]["docs-retention"]["default"] == 0
    body = (WORKFLOWS / "reusable-docs-pages.yml").read_text(encoding="utf-8")
    assert "keeping all versions" in body, "pruner missing the cap<=0 keep-all branch"
    assert body.index("cap <= 0") < body.index("versions[:cap]"), "keep-all guard must precede the slice"


def test_registry_publishes_run_in_deployment_environments() -> None:
    # finding 7: PyPI/GHCR publishes get the same platform-level environment gate the
    # Pages/App Store deploys already have.
    pypi = _load("reusable-pypi-publish.yml")
    assert pypi["jobs"]["publish"]["environment"]["name"] == "${{ inputs.environment-name }}"
    ghcr = _load("reusable-docker-ghcr.yml")
    assert ghcr["jobs"]["docker"]["environment"]["name"] == "${{ inputs.environment-name }}"


def test_ghcr_publishes_only_scanned_digests() -> None:
    # C12-W3: no rebuild between scan and publish — the workflow must scan local OCI
    # archives and promote those exact bytes by digest, asserting pushed == scanned.
    body = (WORKFLOWS / "reusable-docker-ghcr.yml").read_text(encoding="utf-8")
    assert "docker/build-push-action" not in body, "scan-then-rebuild reintroduced (C12-W3)"
    assert '--output "type=oci,dest=oci/${slug}.tar"' in body, "build must emit a local OCI archive"
    assert '--input "oci/${slug}.tar"' in body, "trivy must scan the archive, not a rebuilt image"
    assert "skopeo copy --digestfile" in body, "push must promote the archive bytes"
    assert '"${pushed_digest}" != "${local_digest}"' in body, "pushed==scanned digest assert missing"
    assert body.index("trivy image") < body.index("skopeo copy"), "scan must precede push"


def test_non_pushing_checkouts_do_not_persist_credentials() -> None:
    # finding 6: the job token must not sit in .git/config while consumer/build code
    # runs. Only workflows that legitimately push (or fetch) from the checkout keep
    # credentials: the release write job (pushes tags/branches; its derive job is
    # pinned to false by the split test), the gate (post-checkout `git fetch origin`),
    # and the drift automation (open_or_update_proposal pushes the proposal branch
    # from the working tree).
    exempt = {"reusable-release.yml", "reusable-release-gate.yml", "reusable-consumer-automation.yml"}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name in exempt:
            continue
        wf = _load(path.name)
        for job_name, job in (wf.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps", []) or []:
                if not str(step.get("uses", "")).startswith("actions/checkout"):
                    continue
                assert (step.get("with") or {}).get("persist-credentials") is False, (
                    f"{path.name}:{job_name}: checkout must set persist-credentials: false"
                )


def test_release_workflow_splits_derive_from_write_job() -> None:
    # C12-W1: the heavy derive phase (pip install + aviato over full history) must hold
    # NO write token; only the propose/tag job gets contents/pull-requests write, and
    # nothing is granted at workflow level.
    wf = _load("reusable-release.yml")
    assert wf["permissions"] == {}, "reusable-release must grant nothing at workflow level"
    derive = wf["jobs"]["derive"]
    assert derive["permissions"] == {"contents": "read"}
    assert "GH_TOKEN" not in (derive.get("env") or {}), "derive must not receive the job token"
    checkout = next(s for s in derive["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"].get("persist-credentials") is False
    release = wf["jobs"]["release"]
    assert release["permissions"] == {"contents": "write", "pull-requests": "write"}
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
    for name, job_name in (
        ("reusable-node-ci.yml", "node-ci"),
        # C12-W4: docs publish is split into build (untrusted, npm-installing) and
        # deploy (privileged) jobs; the npm hardening lives in build.
        ("reusable-docs-pages.yml", "build"),
    ):
        wf = _load(name)
        on_block = wf.get("on") or wf.get(True)
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


def test_node_service_scaffold_uses_npm11_capable_node_default() -> None:
    body = (SCAFFOLD_FILES / "wf-node-service.yml").read_text(encoding="utf-8")
    assert 'node-version: "24"' in body
    assert 'node-version: "22"' not in body
    assert 'lint-command: "npx --no-install eslint ."' in body


def test_docs_publish_lints_docusaurus_site_after_install() -> None:
    wf = _load("reusable-docs-pages.yml")
    on_block = wf.get("on") or wf.get(True)
    lint_input = on_block["workflow_call"]["inputs"]["lint-command"]
    assert lint_input["default"] == "npm run lint --if-present"
    steps = wf["jobs"]["build"]["steps"]
    install = next(s for s in steps if s.get("name") == "Install")
    lint = next(s for s in steps if s.get("name") == "Lint docs site")
    assert steps.index(install) < steps.index(lint)
    assert "LINT_COMMAND" in lint.get("env", {})


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
        assert needs == "privilege-probe", message

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


def test_consumer_automation_settings_drift_token_is_optional_and_read_only() -> None:
    # §5.6/§11.3: settings drift READS branch protection + rulesets, which the platform
    # GITHUB_TOKEN cannot do (there is no `administration` workflow-permission scope — a
    # common wrong fix that actionlint rejects). Detection therefore takes an OPTIONAL
    # operator-supplied admin token via the `settings-token` secret, used read-only.
    wf = _load("reusable-consumer-automation.yml")

    # The bogus scope must never reappear; permissions stay the low-privilege report set.
    assert "administration" not in wf["permissions"]
    assert wf["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "issues": "write",
    }

    # The optional admin token is declared (not required).
    # (YAML 1.1 parses the `on:` key as boolean True, hence wf.get(True).)
    on_block = wf.get("on") or wf.get(True)
    settings_secret = on_block["workflow_call"]["secrets"]["settings-token"]
    assert settings_secret.get("required") is False

    # §11.2/§5.6 least-privilege: the admin settings-token must NOT be a job-wide GH_TOKEN
    # (that would expose it to the install step and the file-drift WRITES). It is scoped to
    # the single read-only settings-drift step; file drift runs under the platform token.
    job = wf["jobs"]["drift-report"]
    assert "settings-token" not in str(job.get("env", {})), "admin token must not be job-wide env"
    steps = job["steps"]
    file_step = next(s for s in steps if "--file-only" in s.get("run", ""))
    assert "github.token" in file_step.get("env", {}).get("GH_TOKEN", "")
    assert "settings-token" not in str(file_step.get("env", {})), "file-drift step must not see the admin token"
    settings_step = next(s for s in steps if "--settings-only" in s.get("run", ""))
    assert "settings-token" in str(settings_step.get("env", {})), "settings-drift step must receive the admin token"

    # The scaffolded caller (read as text — it carries {{ }} placeholders) passes the
    # consumer's optional secret through to the reusable workflow.
    caller = (SCAFFOLD_FILES / "wf-drift.yml").read_text(encoding="utf-8")
    assert "settings-token: ${{ secrets.AVIATO_SETTINGS_TOKEN }}" in caller
    assert "administration:" not in caller


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
        assert jobs[name].get("needs") == "privilege-probe", f"{name} must run after the privilege probe"

    heartbeat_needs = jobs["heartbeat"].get("needs", [])
    for name in scan_jobs:
        assert name in heartbeat_needs, f"heartbeat must depend on {name} so a skipped scan is detectable"

    gate_steps = [step.get("name", "") for step in jobs["heartbeat"].get("steps", []) if isinstance(step, dict)]
    assert any("Gate" in name for name in gate_steps), "missing 'Gate on required scans' step"


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
        "reusable-consumer-automation.yml",
        "reusable-common-lint.yml",
    ):
        body = (WORKFLOWS / name).read_text()
        m = guard_re.search(body)
        assert m, f"{name} missing the AVIATO_REF pin guard"
        # The guard must run BEFORE the pinned install.
        assert body.index("AVIATO_REF") < body.index(
            'pip install "git+https://github.com/amattas/aviato@${AVIATO_REF}"'
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

    def holds_token(perms: dict) -> bool:
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
    # The privileged publish job must depend on build (artifacts cross the boundary) and run NO eval.
    assert jobs["publish"].get("needs") == "build" or "build" in (jobs["publish"].get("needs") or [])
    assert "eval " not in _json.dumps(jobs["publish"].get("steps", [])), "publish job must run no build code"


def test_pypi_artifact_upload_download_paths_are_symmetric() -> None:
    # R4-5-D: the build job uploads the dist+sbom and the publish job downloads them; the paths must
    # reconstruct symmetrically so the attest subject-path / pypi packages-dir (which read
    # `<working-directory>/<packages-dir>`) resolve to the actual files. upload-artifact roots the
    # artifact at the least-common-ancestor of its `path:` entries; downloading to `path: <wd>`
    # re-roots there. The round-trip is exact IFF every uploaded path is under `<wd>` and download
    # extracts to exactly `<wd>` (a wrong download path would yield `<wd>/<wd>/...` or a missing dir).
    wf = _load("reusable-pypi-publish.yml")
    steps = {
        "build": wf["jobs"]["build"]["steps"],
        "publish": wf["jobs"]["publish"]["steps"],
    }

    def _step(job: str, action_substr: str) -> dict:
        return next(s for s in steps[job] if action_substr in (s.get("uses") or ""))

    up = _step("build", "upload-artifact")["with"]
    down = _step("publish", "download-artifact")["with"]
    wd = "${{ inputs.working-directory }}"

    assert up["name"] == down["name"], "upload/download artifact names must match"
    # Every uploaded path is under <wd> (so the least-common-ancestor is <wd>).
    upload_paths = [p for p in str(up["path"]).splitlines() if p.strip()]
    assert upload_paths, "upload step lists no paths"
    for p in upload_paths:
        assert p.strip().startswith(f"{wd}/"), f"upload path not under working-directory: {p!r}"
    # Download must extract to exactly <wd> so the tree reconstructs at <wd>/<packages-dir>/... .
    assert down["path"] == wd, f"download path {down['path']!r} must be exactly {wd!r}"


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
