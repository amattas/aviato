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
        ("reusable-release.yml", "release"),
        ("reusable-consumer-automation.yml", "drift-report"),
    ):
        wf = _load(name)
        install = next(s for s in wf["jobs"][job_name]["steps"] if s.get("name") == "Install Aviato")
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
        ("reusable-docs-pages.yml", "publish-docs"),
    ):
        wf = _load(name)
        on_block = wf.get("on") or wf.get(True)
        assert on_block["workflow_call"]["inputs"]["node-version"]["default"] == "24"
        steps = wf["jobs"][job_name]["steps"]
        harden = next(s for s in steps if s.get("name") == "Harden npm install behavior")
        install = next(s for s in steps if s.get("name") == "Install")
        run = harden["run"]
        assert 'npm_version="$(npm --version)"' in run
        assert '[[ "${npm_major}" =~ ^[0-9]+$ ]]' in run
        assert '[ "${npm_major}" -lt 11 ]' in run
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
    steps = wf["jobs"]["publish-docs"]["steps"]
    install = next(s for s in steps if s.get("name") == "Install")
    lint = next(s for s in steps if s.get("name") == "Lint docs site")
    assert steps.index(install) < steps.index(lint)
    assert "LINT_COMMAND" in lint.get("env", {})


def test_common_lint_blocks_unsafe_npx_registry_fetches() -> None:
    wf = _load("reusable-common-lint.yml")
    steps = wf["jobs"]["common-lint"]["steps"]
    npx = next(s for s in steps if s.get("name") == "npx registry fetch pin (blocking)")
    run = npx["run"]
    assert "npx may fetch an unpinned registry tool" in run
    assert "--no-install" in run
    assert "exact_package" in run


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
    jitter = next((s for s in probe_steps if "sleep" in s.get("run", "") and "RANDOM" in s.get("run", "")), None)
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
    assert wf["permissions"] == {"contents": "write", "pull-requests": "write", "issues": "write"}

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
