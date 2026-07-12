# Repository Integrity and Release Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every confirmed repository-integrity, release, deployment, security, validation, and documentation finding from the 2026-07-12 audit, then prove the corrected paths locally and against the live amattas/aviato repository.

**Architecture:** Harden the agnostic core first (confined filesystem mutations, validated declarations, fail-closed integrity state, stable drift/profile identities), then repair the GitHub binding and reusable workflows (honest SHA attribution, explicit security enforcement, consumer-local PyPI publishing, first-party Pages deployment, release-status bridging). Keep target-specific behavior in aviato/library data and GitHub-specific behavior outside aviato/core. End with one source-of-truth cleanup and operator-run platform verification; no green unit suite substitutes for the live gates.

**Tech Stack:** Python 3.12, pytest 9, mypy 2 strict mode, Ruff, Black, PyYAML, GitHub Actions, GitHub CLI/REST API, CodeQL v4, Trivy, Zensical 0.0.50, mike full-SHA pin, PyPI Trusted Publishing, GitHub Pages custom workflows.

## Audit Baseline

- Audited commit: fc4194c on main, matching origin/main.
- Preserve the unrelated untracked OVERLAY.md; do not stage, edit, or delete it.
- CI-parity local gate passed in an isolated Python 3.12.11 environment: Aviato validation, Ruff, Black, package-only strict mypy, yamllint, shellcheck, actionlint, wheel package-data validation, and 815 tests.
- Coverage measurement passed at 87 percent total. The requirements deliberately make a numeric threshold opt-in, so this plan does not invent a fail-under gate.
- Extending strict mypy to aviato plus tests currently fails with 234 errors in 34 files.
- Reproduced locally: a symlinked .github directory lets scaffold write outside the consumer root; language-variant=ruby is accepted and silently omits package.json; package metadata is 0.3.0 while aviato.__version__ is 0.1.0.
- Live GitHub state: release PR 42 is blocked because dispatch runs do not satisfy PR required contexts; one open high CodeQL alert exists while the security heartbeat is green; Pages is legacy main-root/Jekyll and its latest build failed; Dependabot security updates are disabled; the live branch ruleset has no code_scanning rule and carries an interim PR bypass; the live tag ruleset lacks the rejected metadata rule.
- Current Library seed state is stale: .github/aviato.seed.json records removed Docusaurus files and omits website/zensical.toml.

## External Constraints Verified During Audit

- PyPI currently cannot register a reusable workflow as a Trusted Publisher; the OIDC publish job must live in the consumer's registered workflow: https://docs.pypi.org/trusted-publishers/troubleshooting/
- GitHub states that a Pages source-branch commit pushed by an Actions workflow with GITHUB_TOKEN does not trigger a Pages build: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- Code-scanning merge protection is a distinct ruleset rule and threshold, not an inference from a successful CodeQL workflow job: https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/manage-your-configuration/set-merge-protection
- workflow_run uses default-branch event context, so custom release refs must be resolved and threaded explicitly: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- CodeQL analyze supports explicit ref and sha inputs; all SARIF producers in one scan must share them: https://github.com/github/codeql-action/blob/main/analyze/action.yml

## Global Constraints

- Start in an isolated worktree using superpowers:using-git-worktrees. Suggested branch: codex/repository-integrity-release-hardening.
- Before implementation, create a Python 3.12 environment and install all gates:

        uv venv --python 3.12 .venv
        uv pip install --python .venv/bin/python -e '.[dev]'
        export PATH="$PWD/.venv/bin:$PATH"

- Use test-driven development for every behavior change: add the narrow failing test, run it and record the expected failure, implement the smallest complete change, rerun the narrow test, then run the affected subsystem.
- Never hand-edit generated examples under templates/. Edit aviato/library/scaffold/files/wf-*.yml, then run python scripts/regen-templates.py and validate parity.
- Keep aviato/core agnostic. GitHub, PyPI, Pages, CodeQL, Python, Node, Swift, and product-specific names belong in bindings, plug-in data, or templates, not core control flow.
- Preserve existing section numbers under docs/requirements. Update a numbered section in place and keep tests/test_docs_index.py green.
- All platform writes in Task 20 are explicit operator checkpoints. Tasks 1-19 must be locally testable without mutating GitHub, PyPI, Pages, or App Store Connect.
- Do not dismiss the current CodeQL alert by hand. Change the misleading local name, prove no secret value is printed, and let a new analysis close it.
- Do not remove the interim live ruleset bypass until the release-PR status bridge is proven on a real release PR.
- Commit after each green task using the commit message named in that task. Do not combine security, release, and deployment migrations into one rollback unit.

## Finding-to-Task Traceability

| ID | Priority | Confirmed finding | Resolution task |
|---|---:|---|---:|
| F-01 | P1 | Managed writes/deletes follow symlinked path components outside the consumer root | 1 |
| F-02 | P1 | Declaration variables bypass enum, boolean, required, secret, and unknown-name validation during materialization | 2 |
| F-03 | P2 | Missing/corrupt seed sidecars silently self-baseline current content; the Library sidecar is stale | 3 |
| F-04 | P2 | Normative resolved-variable input identity is absent from managed drift markers | 4 |
| F-05 | P2 | Cross-version profile identity checking is incomplete and dormant in the shipped re-pin path | 5 |
| F-06 | P1 | Runtime version 0.1.0 disagrees with package/release metadata 0.3.0 | 6 |
| F-07 | P1 | Custom-ref CodeQL/Trivy uploads and heartbeats can be attributed to the event SHA instead of the scanned SHA | 7 |
| F-08 | P1 | High/critical CodeQL findings do not fail release scans or the packaged/live branch ruleset | 8 |
| F-09 | P2 | workflow_run release gating uses GITHUB_SHA instead of the release tag commit | 9 |
| F-10 | P2 | workflow_dispatch verification does not create PR-visible required status contexts | 10 |
| F-11 | P1 | Consumer PyPI Trusted Publishing cannot work while the OIDC publish job lives in a cross-repo reusable workflow | 11 |
| F-12 | P1 | GITHUB_TOKEN pushes to gh-pages do not trigger branch-source Pages builds; current Pages is misconfigured | 12 |
| F-13 | P2 | Free/personal repositories reject tag metadata rules; apply leaves partial state and live protections are incomplete | 13 |
| F-14 | P2 | Two non-pushing checkouts persist credentials; Apple reviewer/receipt checks are incomplete | 14 |
| F-15 | P2 | Doctor/fleet/CLI health and slug validation paths are inconsistent or stale | 15 |
| F-16 | P2 | Validation has a shadowable build probe, an unbounded subprocess, and fail-open/parity gaps | 16 |
| F-17 | P2 | Scaffold/profile contract has Python, Swift, variable, slug, and generated-copy hygiene debt | 17 |
| F-18 | P2 | Tests are excluded from strict typing; several platform fakes have drifted signatures | 18 |
| F-19 | P3 | Requirements, README, old plans, and backlogs contain stale or contradictory state | 19 |
| F-20 | P1 | Unit tests cannot prove real CodeQL, release, PyPI, Pages, ruleset, or App Store behavior | 20 |

---

### Task 1: Confine every consumer-tree read, write, replace, and delete

**Files:**

- Create: aviato/core/pathguard.py
- Modify: aviato/core/scaffold.py
- Modify: aviato/core/diagnosis.py
- Modify: aviato/core/offboarding.py
- Modify: aviato/core/declaration.py
- Modify: aviato/core/registry.py
- Modify: aviato/cli.py
- Create: tests/core/test_pathguard.py
- Test: tests/core/test_scaffold.py
- Test: tests/core/test_diagnosis.py
- Test: tests/core/test_offboarding.py

**Interfaces:**

- Add confined_target(root: Path, relative: str, *, operation: str) -> Path.
- Reject absolute paths, parent traversal, an empty/dot path, backslash-rooted paths, and every existing symlink component, including the leaf.
- Resolve the root once and require each existing component and the final parent to remain under it. Raise a new PathConfinementError derived from AviatoError, naming the relative output and operation.
- Call the guard immediately before reads and immediately before each atomic replace/unlink. Registry validation remains defense in depth; consumer filesystem confinement must not depend on trusted Library data.
- Change declaration writes to a confined atomic root/relative operation; every CLI declaration read passes the consumer root and .github/aviato.yaml through the guard first. Registry profile/module/template reads use the same guard against a symlinked module-source tree.

- [ ] **Step 1: Add red tests for the reproduced escape.** Cover a .github symlink for scaffold, a nested parent symlink for diagnosis, a symlinked workflow leaf for offboard, and symlinked .github/aviato.yaml plus .github/aviato.seed.json. Assert the outside target is byte-identical and the operation raises PathConfinementError.

        def test_scaffold_rejects_symlinked_parent(tmp_path: Path) -> None:
            outside = tmp_path.parent / f"{tmp_path.name}-outside"
            outside.mkdir()
            (tmp_path / ".github").symlink_to(outside, target_is_directory=True)
            with pytest.raises(PathConfinementError, match=".github/workflows/ci.yml"):
                scaffold(
                    tmp_path,
                    [ScaffoldItem(".github/workflows/ci.yml", "name: ci\n", "#")],
                    profile="p",
                    version="1",
                )
            assert not (outside / "workflows/ci.yml").exists()

- [ ] **Step 2: Run the red tests.**

        python -m pytest tests/core/test_pathguard.py tests/core/test_scaffold.py tests/core/test_diagnosis.py tests/core/test_offboarding.py -q

  Expected: the new symlink cases fail; existing path traversal tests remain green.

- [ ] **Step 3: Implement pathguard and replace direct root / output joins at all mutation/read boundaries.** Preserve atomic-write mode behavior. Do not follow a leaf symlink to inspect its mode; reject it before path.stat(). Preflight all offboard targets before the first mutation so one bad path cannot cause a partial offboard.

- [ ] **Step 4: Add a repository-wide guard test.** In tests/core/test_pathguard.py, AST-scan scaffold.py, diagnosis.py, offboarding.py, declaration.py, registry.py, and CLI declaration sites so direct root / artifact.output_path or root / output mutation sites cannot be reintroduced without confined_target.

- [ ] **Step 5: Run subsystem and agnosticism gates.**

        python -m pytest tests/core/test_pathguard.py tests/core/test_scaffold.py tests/core/test_diagnosis.py tests/core/test_offboarding.py tests/core/test_selfcheck.py -q
        ruff check aviato/core/pathguard.py aviato/core/scaffold.py aviato/core/diagnosis.py aviato/core/offboarding.py aviato/core/declaration.py aviato/core/registry.py aviato/cli.py tests/core
        mypy --strict aviato/core/pathguard.py aviato/core/scaffold.py aviato/core/diagnosis.py aviato/core/offboarding.py aviato/core/declaration.py aviato/core/registry.py aviato/cli.py

  Expected: all pass; the original /tmp symlink reproduction now raises and creates no outside file.

- [ ] **Step 6: Commit.**

        git add aviato/core/pathguard.py aviato/core/scaffold.py aviato/core/diagnosis.py aviato/core/offboarding.py aviato/core/declaration.py aviato/core/registry.py aviato/cli.py tests/core
        git commit -m "fix(core): confine consumer filesystem mutations"

---

### Task 2: Validate declaration variables before every resolution/materialization path

**Files:**

- Modify: aviato/core/variables.py
- Modify: aviato/core/onboarding.py
- Modify: aviato/core/diagnosis.py
- Test: tests/core/test_variables.py
- Test: tests/core/test_onboarding.py
- Test: tests/core/test_diagnosis.py
- Test: tests/test_cli_sync.py

**Interfaces:**

- Add resolve_declared_variables(specs: Sequence[VariableSpec], values: Mapping[str, Any]) -> dict[str, Any].
- It must reject unknown names, coerce/validate booleans and enums through the existing _coerce path, fail on missing required values, and reject any non-None secret-typed declaration value.
- resolved_artifacts must call this function before constraints, conditions, derived variables, or render. Callers may no longer supply a partially trusted raw mapping.

- [ ] **Step 1: Add a parameterized red test.** Include language-variant=ruby, docs-mode=not-a-bool, an unknown typo, a missing required variable in a minimal registry, and a secret-typed value. The reproduced node-service case must assert DeclarationError rather than a 13-file artifact set with no package.json.

        @pytest.mark.parametrize("value", ["ruby", "", 1, True])
        def test_materialize_rejects_invalid_enum(value: object) -> None:
            with pytest.raises(DeclarationError, match="language-variant"):
                materialize_items(
                    Registry(MODULE_SOURCE_ROOT),
                    "node-service",
                    {"language-variant": value},
                    pin="0",
                )

- [ ] **Step 2: Run the red tests.**

        python -m pytest tests/core/test_variables.py tests/core/test_onboarding.py tests/test_cli_sync.py -q -k "declared or invalid_enum or unknown_variable or secret"

  Expected: the invalid enum and unknown-name cases fail because the current renderer accepts/drops them.

- [ ] **Step 3: Implement one validation path.** Reuse resolve_variables rather than duplicating coercion. Check unknown names first, call resolve_variables with the declaration tier, then enforce the secret-name rule. Replace the current defaults-plus-raw-update block in resolved_artifacts with the validated result.

- [ ] **Step 4: Prove every materialization caller fails consistently.** Add CLI tests for sync, doctor, drift-report, scan, and repin with the same invalid declaration; each must return exit 2 with the variable name and must not write files or open proposals.

- [ ] **Step 5: Run the affected suites.**

        python -m pytest tests/core/test_variables.py tests/core/test_onboarding.py tests/core/test_diagnosis.py tests/test_cli_sync.py tests/test_cli_drift_report.py tests/test_cli_scan.py tests/test_cli_repin_offboard.py -q
        ruff check aviato/core/variables.py aviato/core/onboarding.py aviato/core/diagnosis.py tests
        mypy --strict aviato/core/variables.py aviato/core/onboarding.py aviato/core/diagnosis.py

- [ ] **Step 6: Commit.**

        git add aviato/core/variables.py aviato/core/onboarding.py aviato/core/diagnosis.py tests/core tests/test_cli_sync.py tests/test_cli_drift_report.py tests/test_cli_scan.py tests/test_cli_repin_offboard.py
        git commit -m "fix(core): validate declared variables before rendering"

---

### Task 3: Make seed-once integrity state explicit and fail closed

**Files:**

- Modify: aviato/core/scaffold.py
- Modify: aviato/core/diagnosis.py
- Modify: aviato/cli.py
- Modify: aviato/validation.py
- Modify: .github/aviato.seed.json (generated through the new explicit rebaseline path)
- Test: tests/core/test_scaffold.py
- Test: tests/core/test_diagnosis.py
- Test: tests/test_cli_sync.py
- Test: tests/test_validation_negative.py

**Interfaces:**

- Replace read_sidecar returning a bare dict with SeedSidecar(status: Literal["ok", "missing", "corrupt"], hashes: dict[str, str]).
- Add ScaffoldResult.seed_integrity_unknown and a baseline_existing_seeds: bool = False keyword to scaffold.
- Fresh onboarding may set baseline_existing_seeds=true after its dry-run enumerates every pre-existing operator-owned seed; no prior Aviato baseline exists yet. For an already-adopted repository, only sync --rebaseline-seeds may set it. Print every adopted baseline before writing it.
- Diagnosis must report missing/corrupt sidecar state and missing expected seed records as broken, not clean and not an exception that aborts a fleet scan.
- Rebaseline output must contain exactly the current resolved seed-once output set: add current files, preserve reviewed current hashes, and remove obsolete keys.

- [ ] **Step 1: Replace the self-heal tests with red fail-closed tests.** Missing and corrupt sidecars in an adopted repository with an existing seed file must produce seed_integrity_unknown and no writes. A missing sidecar with an absent seed file may create the file and its initial record. Add CLI tests showing fresh onboard --write records each enumerated pre-existing seed, while later sync requires --rebaseline-seeds and prints every explicitly adopted path.

- [ ] **Step 2: Add a bootstrap parity test for the Library.** Resolve aviato-library, collect every seed-once output, and assert .github/aviato.seed.json has exactly those existing outputs. This must fail on the current Docusaurus keys and missing website/zensical.toml.

- [ ] **Step 3: Run the red tests.**

        python -m pytest tests/core/test_scaffold.py tests/core/test_diagnosis.py tests/test_cli_sync.py tests/test_validation_negative.py -q -k "sidecar or seed"

  Expected: failures demonstrate silent self-baselining and the stale Library sidecar.

- [ ] **Step 4: Implement preflight-before-mutation semantics.** Parse and validate the full sidecar before any managed write. On unknown state, return/raise a clean AviatoError naming --rebaseline-seeds. Keep fleet diagnosis report-only. Write the sidecar atomically through the confined path from Task 1.

- [ ] **Step 5: Review and explicitly regenerate the Library baseline.** First inspect every current seed output, then run:

        aviato sync . --rebaseline-seeds
        git diff -- .github/aviato.seed.json

  Expected: removed Docusaurus entries disappear; website/zensical.toml and every other current seed output are present; no unrelated file changes.

- [ ] **Step 6: Run subsystem checks.**

        python -m pytest tests/core/test_scaffold.py tests/core/test_diagnosis.py tests/test_cli_sync.py tests/test_validation_negative.py -q
        aviato validate

- [ ] **Step 7: Commit.**

        git add aviato/core/scaffold.py aviato/core/diagnosis.py aviato/cli.py aviato/validation.py .github/aviato.seed.json tests/core tests/test_cli_sync.py tests/test_validation_negative.py
        git commit -m "fix(scaffold): fail closed on unknown seed integrity"

---

### Task 4: Record and compare canonical resolved-variable input identity

**Files:**

- Modify: aviato/core/marker.py
- Modify: aviato/core/model.py
- Modify: aviato/core/onboarding.py
- Modify: aviato/core/scaffold.py
- Modify: aviato/core/diagnosis.py
- Modify: aviato/cli.py
- Test: tests/core/test_marker.py
- Test: tests/core/test_scaffold.py
- Test: tests/core/test_diagnosis.py
- Test: tests/core/test_filedrift.py

**Interfaces:**

- Add canonical_input_hash(values: Mapping[str, Any]) -> str using sorted compact JSON, UTF-8, SHA-256. Inputs are the fully resolved, coerced, non-secret profile variables plus docs; exclude the Library version so a pin-only move remains a no-op.
- Extend MarkerInfo with input_hash: str | None and managed markers with inputs=<sha256>. Parsing remains backward compatible: old markers parse with None and classify mergeable so one sync restamps them.
- Add input_hash to ResolvedArtifact, ScaffoldItem, and ExpectedArtifact. The renderer computes it once from the validated resolved inputs and threads it through every path.
- Classification order stays safety-first: foreign/unknown marker and hand-edited-body dirty drift win; otherwise a body-hash or input-hash mismatch is mergeable drift.

- [ ] **Step 1: Add marker grammar red tests.** Assert round-trip of inputs=<64 hex>, rejection of malformed input hashes, and backward-compatible parsing of a legacy marker.

- [ ] **Step 2: Add the normative behavior test.** Create a template whose body does not reference an optional variable. Scaffold with variable A, then diagnose with variable B. Body hashes are equal, but the result must be mergeable-drift because resolved input identity changed. A version-only change must stay clean.

- [ ] **Step 3: Run red tests.**

        python -m pytest tests/core/test_marker.py tests/core/test_scaffold.py tests/core/test_diagnosis.py tests/core/test_filedrift.py -q

- [ ] **Step 4: Implement canonical hashing and thread the field end to end.** Never include secret values in the canonical payload or error output. Update render_managed and all direct ScaffoldItem/ExpectedArtifact test factories.

- [ ] **Step 5: Add a compatibility migration test.** A clean legacy marker without inputs must be mergeable, sync must restamp it without changing the body, and the next diagnosis must be clean.

- [ ] **Step 6: Run core suites and validate.**

        python -m pytest tests/core -q
        aviato validate

- [ ] **Step 7: Commit.**

        git add aviato/core/marker.py aviato/core/model.py aviato/core/onboarding.py aviato/core/scaffold.py aviato/core/diagnosis.py aviato/cli.py tests/core
        git commit -m "feat(drift): bind managed markers to resolved inputs"

---

### Task 5: Give profiles an explicit stable identity that re-pin can actually verify

**Files:**

- Modify: aviato/core/model.py
- Modify: aviato/core/registry.py
- Modify: aviato/core/declaration.py
- Modify: aviato/core/onboarding.py
- Modify: aviato/core/repin.py
- Create: aviato/library_source.py
- Modify: aviato/cli.py
- Modify: aviato/library/aviato-library.yaml
- Modify: aviato/library/python-library.yaml
- Modify: aviato/library/python-service.yaml
- Modify: aviato/library/python-component.yaml
- Modify: aviato/library/node-service.yaml
- Modify: aviato/library/swift-app.yaml
- Modify: docs/requirements/core/consumer-contract.md
- Modify: docs/requirements/modules/versioning/repin.md
- Test: tests/core/test_registry.py
- Test: tests/core/test_declaration.py
- Test: tests/core/test_repin.py
- Create: tests/test_library_source.py
- Test: tests/test_cli_repin_offboard.py

**Interfaces:**

- Add required identity to Profile manifests, using stable values aviato-profile/<profile-name>/v1.
- Add profile_identity: str | None to Declaration and serialize it as profile-identity.
- Add a binding-layer fetch_library_registry(repository: str, pin: str) context manager. Resolve the published ref to one commit with gh, download that commit's archive, safely extract regular files under aviato/library only, and return Registry(extracted/library). Reject archive traversal, symlinks, missing manifests, or a ref/SHA mismatch.
- Onboarding always writes the resolved profile identity. A legacy declaration may be backfilled only from the registry fetched at its declared pin and must print the declaration change.
- Re-pin compares declaration.profile_identity with the fetched target registry identity, then uses that same target registry for newly-required variables, orphaned overrides, and materialization. A mismatch or missing identity refuses before changing the pin. This removes the dormant single-installed-registry behavior without confusing legitimate profile evolution with repurposing.

- [ ] **Step 1: Write red registry/declaration tests.** Missing/empty identity in a profile manifest is CompositionError. profile-identity round-trips through YAML. Unknown declaration keys still fail.

- [ ] **Step 2: Add archive/fetch red tests.** Mock gh ref resolution and archive bytes. Cover exact and floating pins, annotated-tag peeling, safe extraction, path traversal, absolute paths, symlinks, missing aviato/library, mismatched commit, cleanup on success/failure, and no network call when the ref does not resolve.

- [ ] **Step 3: Replace the current shape-digest re-pin tests.** Changing templates, variables, settings, privileges, or version-source while retaining the identity is an evolution and reaches the target registry's migration checks. Changing only identity is a repurpose and raises CompositionError. A legacy declaration with no identity fails with an instruction to sync using its current pin first.

- [ ] **Step 4: Run red tests.**

        python -m pytest tests/core/test_registry.py tests/core/test_declaration.py tests/core/test_repin.py tests/test_library_source.py tests/test_cli_repin_offboard.py -q

- [ ] **Step 5: Implement safe target-registry acquisition and explicit identity.** Keep all gh/archive code outside core. Delete _profile_identity and its misleading full-composition tuple. Feed the fetched registry into plan_repin and materialize_items for local-write and proposal paths; keep newly-required-variable and orphaned-override checks after identity verification.

- [ ] **Step 6: Add identities to all six shipped profiles and update §6.1, §6.5, and §5.12 in place.** Document that the immutable identifier, not a hash of every evolvable field, distinguishes continuity from repurposing, and remove the day-zero limitation text.

- [ ] **Step 7: Add migration coverage.** Start from a legacy declaration, fetch its declared-pin registry, run sync, assert only profile-identity plus expected managed restamps change, then fetch a distinct target registry and successfully plan/re-render a re-pin. An unresolved pin or identity mismatch must not modify the declaration.

- [ ] **Step 8: Run composition, declaration, re-pin, docs-index, and validation gates.**

        python -m pytest tests/core/test_composition.py tests/core/test_registry.py tests/core/test_declaration.py tests/core/test_repin.py tests/test_library_source.py tests/test_cli_repin_offboard.py tests/test_docs_index.py -q
        aviato validate

- [ ] **Step 9: Commit.**

        git add aviato/core aviato/library_source.py aviato/cli.py aviato/library/*.yaml docs/requirements/core/consumer-contract.md docs/requirements/modules/versioning/repin.md tests
        git commit -m "feat(versioning): persist stable profile identities"

---

### Task 6: Derive the runtime version from installed package metadata

**Files:**

- Modify: aviato/__init__.py
- Modify: aviato/validation.py
- Modify: scripts/validate.sh
- Modify: tests/test_cli_release.py
- Modify: tests/test_validation_negative.py
- Modify: tests/test_local_gate.py

**Interfaces:**

- aviato.__version__ must equal importlib.metadata.version("aviato") in an installed/editable environment.
- A source-tree fallback may read project.version from the root pyproject.toml only when distribution metadata is genuinely unavailable; it must return a valid SemVer or fail loudly, never a stale hand-maintained constant.
- Validation must compare project metadata, runtime metadata, and the version exposed by an installed wheel.

- [ ] **Step 1: Add the red parity test.** Replace the hardcoded 0.1.0 CLI assertion with:

        from importlib.metadata import version as distribution_version

        def test_runtime_version_matches_distribution_metadata() -> None:
            assert __version__ == distribution_version("aviato")

  Also build the wheel in a temporary directory, install it into a temporary venv, and assert its imported __version__ equals its METADATA Version field.

- [ ] **Step 2: Run the red tests and capture the current mismatch.**

        python -m pytest tests/test_cli_release.py tests/test_validation_negative.py -q -k version

  Expected: package metadata 0.3.0 does not equal runtime constant 0.1.0.

- [ ] **Step 3: Implement metadata-derived versioning.** Remove the literal. Handle PackageNotFoundError only; do not swallow malformed metadata or arbitrary import errors. Keep aviato.__version__ as the public interface consumed by compatibility gates.

- [ ] **Step 4: Add a release guard.** scripts/validate.sh must run the wheel parity check after build, so a release PR cannot bump pyproject.toml while shipping a different runtime version.

- [ ] **Step 5: Run release and packaging checks.**

        python -m pytest tests/test_cli_release.py tests/test_validation_negative.py tests/test_local_gate.py -q
        AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh

- [ ] **Step 6: Commit.**

        git add aviato/__init__.py aviato/validation.py scripts/validate.sh tests/test_cli_release.py tests/test_validation_negative.py tests/test_local_gate.py
        git commit -m "fix(release): derive runtime version from package metadata"

---

### Task 7: Bind every security scan, SARIF upload, and heartbeat to one resolved ref/SHA

**Files:**

- Modify: .github/workflows/reusable-security-baseline.yml
- Modify: .github/workflows/aviato-docs.yml
- Modify: aviato/library/scaffold/files/wf-docs-python-library.yml
- Modify: aviato/library/scaffold/files/wf-docs-python-service.yml
- Modify: aviato/library/scaffold/files/wf-docs-python-component.yml
- Modify: aviato/library/scaffold/files/wf-docs-node-service.yml
- Modify: aviato/library/scaffold/files/wf-docs-swift-app.yml
- Modify: aviato/cli.py
- Modify: aviato/github_platform.py
- Modify: templates/ (regenerated docs callers)
- Test: tests/test_workflow_guards.py
- Test: tests/test_github_platform.py
- Create: tests/test_cli_doctor.py

**Interfaces:**

- reusable-security-baseline accepts ref and sha. For ordinary PR/push runs both may be empty and resolve to the event ref/SHA; release/docs callers must pass the full tag ref and exact gated SHA.
- A first resolve-target step verifies that ref resolves to sha, emits canonical-ref and analyzed-sha, and checkout uses the SHA.
- Pass those exact outputs to github/codeql-action/analyze and both github/codeql-action/upload-sarif invocations.
- Name the clean heartbeat artifact aviato-security-heartbeat-<analyzed-sha> and include analyzed_ref plus analyzed_sha in its JSON. Default-branch doctor queries the current HEAD-specific name; a release scan can no longer masquerade as a clean scan of a newer default-branch HEAD.

- [ ] **Step 1: Add red YAML-contract tests.** Parse the workflow and assert checkout, CodeQL analyze, and both SARIF uploads consume the same resolve-target outputs. Assert every workflow_run docs caller supplies refs/tags/<release-tag> and the resolved gated SHA.

- [ ] **Step 2: Add red heartbeat tests.** A current-head artifact whose workflow_run.head_sha matches but whose name/content binds another analyzed SHA must not report healthy. An exact current-head artifact must report healthy. An API/read failure stays unknown.

- [ ] **Step 3: Run the red tests.**

        python -m pytest tests/test_workflow_guards.py tests/test_github_platform.py tests/test_cli_doctor.py -q -k "security_ref or sarif or heartbeat_sha"

- [ ] **Step 4: Resolve and bind the target once.** Fetch tags, canonicalize a bare tag input to refs/tags/<tag>, peel annotated tags to commits, compare with the supplied SHA when present, and fail before initialization on any mismatch.

- [ ] **Step 5: Change the misleading CodeQL-alert local variable in aviato/cli.py.** Rename the display-only string secret to secret_marker or classification_marker and add a CLI-output test proving only variable name/type/optional/classification are printed, never a supplied value.

- [ ] **Step 6: Regenerate callers and run guards.**

        python scripts/regen-templates.py
        python -m pytest tests/test_workflow_guards.py tests/test_github_platform.py tests/test_cli_doctor.py tests/test_cli_onboard.py -q
        aviato validate

- [ ] **Step 7: Commit.**

        git add .github/workflows/reusable-security-baseline.yml .github/workflows/aviato-docs.yml aviato/cli.py aviato/github_platform.py aviato/library/scaffold/files templates tests
        git commit -m "fix(security): bind scan evidence to the analyzed commit"

---

### Task 8: Enforce high/critical CodeQL results in workflows and rulesets

**Files:**

- Modify: .github/workflows/reusable-security-baseline.yml
- Modify: aviato/library/rulesets/protect-default-branch.json
- Modify: aviato/library/pipelines.yaml
- Modify: aviato/github.py
- Modify: aviato/github_platform.py
- Modify: docs/requirements/core/principles.md
- Modify: docs/requirements/modules/security/scanning.md
- Test: tests/test_workflow_guards.py
- Test: tests/test_rulesets.py
- Test: tests/test_github.py
- Test: tests/test_github_platform.py

**Interfaces:**

- After CodeQL analyze has finished processing, query open CodeQL alerts for the analyzed ref and fail on rule.security_severity_level high or critical. The query must paginate, distinguish API ambiguity from zero results, and fail closed on ambiguity.
- Upload the clean heartbeat only after CodeQL, dependency, secret, and image gates all pass.
- Add a code_scanning branch-ruleset rule for CodeQL with alerts_threshold=none and security_alerts_threshold=high_or_higher. Keep the required heartbeat status as an availability/freshness signal; it is not a substitute for the code-scanning rule.
- Doctor must report both code-scanning availability and whether the expected CodeQL merge-protection rule/threshold is present.

- [ ] **Step 1: Add red workflow tests.** Assert a dedicated CodeQL severity gate runs after analyze, filters by the resolved ref/tool, paginates, treats high/critical as failure, and is a dependency of heartbeat upload.

- [ ] **Step 2: Add red ruleset tests.** Render every profile's branch ruleset and assert exactly one CodeQL code_scanning rule with the required thresholds. Add live-payload comparison tests so removal or threshold weakening is reported as drift.

- [ ] **Step 3: Run red tests.**

        python -m pytest tests/test_workflow_guards.py tests/test_rulesets.py tests/test_github.py tests/test_github_platform.py -q -k "codeql or code_scanning"

- [ ] **Step 4: Implement the workflow gate and ruleset rule.** Use GH_TOKEN only in the no-consumer-code alert query step. Never print alert bodies or secret-bearing source snippets; print alert number, rule id, severity, and URL.

- [ ] **Step 5: Add a deterministic SARIF canary fixture.** Tests must exercise no alert, medium-only, high, critical, pagination, and API-error outcomes. High/critical fail; medium-only follows the documented threshold and passes.

- [ ] **Step 6: Run security/ruleset suites and validation.**

        python -m pytest tests/test_workflow_guards.py tests/test_rulesets.py tests/test_github.py tests/test_github_platform.py tests/test_pipeline_privileges.py -q
        aviato validate

- [ ] **Step 7: Commit.**

        git add .github/workflows/reusable-security-baseline.yml aviato/library/rulesets/protect-default-branch.json aviato/library/pipelines.yaml aviato/github.py aviato/github_platform.py docs/requirements/core/principles.md docs/requirements/modules/security/scanning.md tests
        git commit -m "fix(security): enforce CodeQL severity at merge and release"

---

### Task 9: Resolve release-gate identity from the release tag, not the event context

**Files:**

- Modify: .github/workflows/reusable-release-gate.yml
- Modify: tests/test_workflow_guards.py
- Modify: docs/requirements/modules/versioning/release.md
- Modify: docs/requirements/modules/deployment/README.md

**Interfaces:**

- Add one resolve-gated-sha step. When release-tag is non-empty, set gated-sha from refs/tags/<tag>^{commit}; otherwise use GITHUB_SHA^{commit} for the classic tag context.
- Every ancestry check, tag equality check, merged-PR query, and required-workflow-run query consumes that output. No later gate step may use raw GITHUB_SHA as the release identity.

- [ ] **Step 1: Add the red descendant-event test.** Build a temporary git history where release tag 1.2.3 points to commit A and event/default-branch SHA is descendant B. Execute the extracted resolve/check shell block and assert gated-sha=A and the ancestry check passes.

- [ ] **Step 2: Add static guard assertions.** Reject GITHUB_SHA references after the resolve step in merged-PR and required-workflow queries; require the gated-sha output instead.

- [ ] **Step 3: Run red tests.**

        python -m pytest tests/test_workflow_guards.py -q -k release_gate

- [ ] **Step 4: Implement and update comments/docs.** Preserve the existing merge-base --is-ancestor behavior. Do not regress to branch-tip equality.

- [ ] **Step 5: Run release workflow guards.**

        python -m pytest tests/test_workflow_guards.py tests/test_cli_release.py tests/core/test_versioning.py -q
        aviato validate

- [ ] **Step 6: Commit.**

        git add .github/workflows/reusable-release-gate.yml tests/test_workflow_guards.py docs/requirements/modules/versioning/release.md docs/requirements/modules/deployment/README.md
        git commit -m "fix(release): gate the release tag commit under workflow-run"

---

### Task 10: Bridge dispatch verification into PR-visible required status contexts

**Files:**

- Modify: aviato/library/scaffold/files/wf-python-library.yml
- Modify: aviato/library/scaffold/files/wf-python-service.yml
- Modify: aviato/library/scaffold/files/wf-python-component.yml
- Modify: aviato/library/scaffold/files/wf-node-service.yml
- Modify: aviato/library/scaffold/files/wf-swift-app.yml
- Modify: aviato/library/pipelines.yaml
- Modify: aviato/validation.py
- Modify: templates/ (regenerated)
- Modify: .github/workflows/aviato-ci.yml (regenerated through bootstrap sync)
- Modify: docs/requirements/modules/versioning/release.md
- Test: tests/test_workflow_guards.py
- Test: tests/test_pipeline_privileges.py
- Test: tests/test_validation_negative.py

**Interfaces:**

- Each caller gets a dispatch-only status-bridge job with if: always() and event_name == workflow_dispatch; needs its verify job, security, and common-lint; permissions are only statuses: write.
- The job checks out no code and executes no consumer command. It posts success/failure commit statuses to github.sha for the exact pipeline status_check contexts: the profile-specific verify context, security / Security baseline heartbeat, and common-lint / Common lint.
- Any needs result other than success maps to failure. API failure fails the bridge job.
- A validation guard derives expected contexts from resolved PipelineModule.status_check data and compares them to every caller bridge; no hand-copied context can drift silently.

- [ ] **Step 1: Add red caller tests.** For all five callers, assert the status bridge is dispatch-only, has statuses:write and no checkout/install/run of repository code, needs the three gating jobs, posts all and only the resolved profile contexts, and maps skipped/cancelled/failure to failure.

- [ ] **Step 2: Add a red validation-negative fixture.** Change one caller context in a temporary copy and assert aviato validate reports that exact caller and expected context.

- [ ] **Step 3: Run red tests.**

        python -m pytest tests/test_workflow_guards.py tests/test_pipeline_privileges.py tests/test_validation_negative.py -q -k "status_bridge or dispatch"

- [ ] **Step 4: Implement the five source callers and the data-driven parity guard.** Add statuses: write to the caller permission union and to the release pipeline's declared privilege union. Keep the token isolated to the no-code bridge job.

- [ ] **Step 5: Regenerate examples and the Library bootstrap caller.**

        python scripts/regen-templates.py
        aviato sync .
        git diff -- templates .github/workflows/aviato-ci.yml

- [ ] **Step 6: Run caller, release, privilege, and validation suites.**

        python -m pytest tests/test_workflow_guards.py tests/test_pipeline_privileges.py tests/test_validation_negative.py tests/core/test_dayzero_profiles.py -q
        aviato validate

- [ ] **Step 7: Commit.**

        git add aviato/library/scaffold/files aviato/library/pipelines.yaml aviato/validation.py templates .github/workflows/aviato-ci.yml docs/requirements/modules/versioning/release.md tests
        git commit -m "fix(release): publish required statuses for release PRs"

---

### Task 11: Move PyPI OIDC publishing into the consumer workflow

**Files:**

- Modify: .github/workflows/reusable-pypi-publish.yml (becomes the build/audit/artifact half only; keep the path for compatibility)
- Modify: aviato/library/scaffold/files/wf-python-library.yml
- Modify: aviato/library/bundles/workflows/python-library-wf.yaml
- Modify: aviato/library/pipelines.yaml
- Modify: aviato/validation.py
- Modify: templates/profile-python-library.yml (regenerated)
- Modify: .github/workflows/aviato-ci.yml (bootstrap sync)
- Modify: docs/requirements/modules/deployment/pypi/requirements.md
- Modify: docs/requirements/modules/onboarding/flow.md
- Test: tests/test_workflow_guards.py
- Test: tests/test_pipeline_privileges.py
- Test: tests/core/test_dayzero_profiles.py
- Test: tests/test_validation_negative.py

**Interfaces:**

- The reusable workflow performs gated checkout, metadata validation, build, dependency audit, SBOM generation, and upload only. It outputs resolved-tag and a fixed artifact name.
- Require consumer-publisher-present: true. A stale caller that invokes the new reusable workflow without a local publisher fails loudly with a sync instruction instead of reporting a successful non-publish.
- The rendered consumer caller contains the normal runs-on publish job and the pinned pypa/gh-action-pypi-publish action. That local job downloads the vetted artifact, re-verifies tag-to-gated-SHA, attests distributions/SBOM, publishes, and confirms index resolution.
- The local publish job alone has environment: pypi, id-token: write, and attestations: write. It runs no install/build/eval command.
- Align the dist handoff on the same supported upload/download artifact major.

- [ ] **Step 1: Add red topology tests.** Assert the reusable workflow contains no pypa publish action and no environment/OIDC publish job. Assert the rendered consumer caller contains it, holds the protected environment and OIDC permissions only in the publish job, consumes the reusable build artifact, and rechecks the exact gated SHA.

- [ ] **Step 2: Add stale-caller and privilege tests.** A call without consumer-publisher-present=true must fail before build. Split pipeline data into the reusable build privilege and local publisher privilege, and verify their union against the caller.

- [ ] **Step 3: Run red tests.**

        python -m pytest tests/test_workflow_guards.py tests/test_pipeline_privileges.py tests/core/test_dayzero_profiles.py tests/test_validation_negative.py -q -k pypi

- [ ] **Step 4: Refactor the reusable workflow.** Preserve the existing tag validation, C12-W2 check, isolated project dependency audit, SBOM, and artifact contents. Remove every OIDC/publish step from it. Use an explicit one-day artifact retention and if-no-files-found:error.

- [ ] **Step 5: Implement the local publisher in the authoritative source caller.** Keep the publish action pinned to the existing full digest. The TestPyPI repository URL is a caller variable/input, not a stored token.

- [ ] **Step 6: Regenerate and bootstrap-sync.**

        python scripts/regen-templates.py
        aviato sync .

- [ ] **Step 7: Run all PyPI/release/parity checks.**

        python -m pytest tests/test_workflow_guards.py tests/test_pipeline_privileges.py tests/core/test_dayzero_profiles.py tests/test_cli_release.py -q
        aviato validate

- [ ] **Step 8: Commit.**

        git add .github/workflows/reusable-pypi-publish.yml aviato/library templates .github/workflows/aviato-ci.yml aviato/validation.py docs/requirements/modules/deployment/pypi/requirements.md docs/requirements/modules/onboarding/flow.md tests
        git commit -m "fix(pypi): publish through the consumer trusted identity"

---

### Task 12: Serve versioned docs through a same-run GitHub Pages deployment

**Files:**

- Modify: .github/workflows/reusable-docs-pages.yml
- Modify: starter/docs-site/docs.yml
- Modify: starter/README.md
- Modify: aviato/library/pipelines.yaml
- Modify: aviato/library/aviato-library.yaml
- Modify: aviato/library/python-library.yaml
- Modify: aviato/library/python-service.yaml
- Modify: aviato/library/python-component.yaml
- Modify: aviato/library/node-service.yaml
- Modify: aviato/library/swift-app.yaml
- Modify: aviato/library/scaffold/files/wf-docs-*.yml
- Modify: .github/aviato.yaml (enable serving for this Library)
- Modify: aviato/github.py
- Modify: aviato/github_platform.py
- Modify: aviato/cli.py
- Modify: templates/ (regenerated)
- Modify: docs/requirements/modules/deployment/docs-site/requirements.md
- Test: tests/test_workflow_guards.py
- Test: tests/test_pipeline_privileges.py
- Test: tests/test_github.py
- Test: tests/test_github_platform.py
- Test: tests/core/test_dayzero_profiles.py

**Interfaces:**

- Add a non-secret boolean profile variable serve-pages, default false. docs=true still builds and pushes the canonical versioned gh-pages branch; serve-pages=true additionally deploys that exact branch tree through GitHub's custom Pages workflow in the same run.
- The read-only build job runs actions/configure-pages and actions/upload-pages-artifact against the exported branch tree. A separate no-consumer-code deploy job consumes that artifact with actions/deploy-pages and only pages: write plus id-token: write.
- The deploy job uses environment github-pages and publishes steps.deployment.outputs.page_url as the environment URL; per-repository concurrency remains non-cancelling so releases cannot race.
- Keep the gh-pages push job isolated with contents: write. A GITHUB_TOKEN branch push is archival/version-state transport, not the Pages trigger.
- Replace pages_source_actions naming with pages_build_type_workflow throughout the binding/doctor output. Probe it only when docs and serve-pages are both enabled.

- [ ] **Step 1: Add red workflow topology tests.** When serve-pages is true, require a Pages artifact and deploy-pages job that needs successful build/push, has pages/id-token permissions, and executes no consumer commands. When false, branch build/push still succeeds and Pages deploy is skipped.

- [ ] **Step 2: Add red profile/render tests.** All docs-capable profiles define serve-pages=false. The Library declaration overrides it true, and the rendered .github/workflows/aviato-docs.yml passes true. An invalid non-boolean is rejected by Task 2's shared validator.

- [ ] **Step 3: Add red doctor tests.** build_type=workflow is healthy only for a serve-enabled declaration; legacy is unhealthy; a 404/schema/API ambiguity remains unknown. A docs-only branch publisher does not emit noisy Pages health.

- [ ] **Step 4: Run red tests.**

        python -m pytest tests/test_workflow_guards.py tests/test_pipeline_privileges.py tests/test_github.py tests/test_github_platform.py tests/core/test_dayzero_profiles.py tests/test_cli_doctor.py -q -k pages

- [ ] **Step 5: Implement same-run deployment in the reusable and starter workflows.** Materialize refs/heads/<docs-branch> into a clean temporary directory, reject symlinks escaping that tree, upload it as the Pages artifact, and deploy it only after the branch push succeeds.

- [ ] **Step 6: Update pipeline privilege data, callers, requirements, and starter instructions.** The instructions must say Pages source is GitHub Actions/workflow, never Deploy from a branch.

- [ ] **Step 7: Regenerate and sync.**

        python scripts/regen-templates.py
        aviato sync .

- [ ] **Step 8: Run docs/profile/doctor validation.**

        python -m pytest tests/test_workflow_guards.py tests/test_pipeline_privileges.py tests/test_github.py tests/test_github_platform.py tests/core/test_dayzero_profiles.py tests/test_cli_doctor.py -q
        aviato validate

- [ ] **Step 9: Commit.**

        git add .github/workflows/reusable-docs-pages.yml .github/workflows/aviato-docs.yml .github/aviato.yaml starter aviato/library aviato/github.py aviato/github_platform.py aviato/cli.py templates docs/requirements/modules/deployment/docs-site/requirements.md tests
        git commit -m "fix(pages): deploy versioned docs through Pages Actions"

---

### Task 13: Make ruleset application capability-aware without weakening other failures

**Files:**

- Modify: aviato/github.py
- Modify: aviato/rulesets.py
- Modify: aviato/cli.py
- Modify: aviato/core/ports.py
- Modify: aviato/github_platform.py
- Modify: docs/requirements/modules/onboarding/flow.md
- Modify: docs/requirements/modules/drift/settings-drift.md
- Test: tests/test_github.py
- Test: tests/test_rulesets.py
- Test: tests/test_cli_apply_rulesets.py
- Test: tests/test_github_platform.py

**Interfaces:**

- Add RulesetApplyResult(message: str, degraded_rules: tuple[str, ...]).
- On an apply, try the complete payload first. Retry exactly once without tag_name_pattern only when GitHub returns HTTP 422 and the response identifies that unsupported metadata-restriction rule. Preserve deletion and non_fast_forward. Any other 422, 4xx, 5xx, auth, network, or malformed response propagates unchanged.
- Print a loud DEGRADED warning naming the repository and missing rule. Return a non-clean degradation in doctor/settings drift so unsupported does not masquerade as fully protected.
- Report all earlier successful repository/ruleset mutations if a later operation fails; never claim transactionality.

- [ ] **Step 1: Add red API tests.** Cover precise metadata-rule 422 followed by successful degraded retry, unrelated 422 with no retry, 403/500 with no retry, update and create endpoints, and a degraded retry that also fails.

- [ ] **Step 2: Add red payload tests.** The degraded payload must differ from desired only by tag_name_pattern and must retain deletion, non_fast_forward, conditions, enforcement, and no bypass actors.

- [ ] **Step 3: Add CLI/report tests.** Dry run says the full rule will be attempted. Apply prints DEGRADED and exits 0 only when the immutability fallback succeeds; doctor/settings drift surface degraded rather than clean.

- [ ] **Step 4: Run red tests.**

        python -m pytest tests/test_github.py tests/test_rulesets.py tests/test_cli_apply_rulesets.py tests/test_github_platform.py -q -k "422 or degraded or metadata"

- [ ] **Step 5: Implement the narrow fallback and structured result.** Do not key solely on the number 422. Keep temporary payload files private and deleted in finally blocks.

- [ ] **Step 6: Run ruleset, reconcile, and CLI suites.**

        python -m pytest tests/test_github.py tests/test_rulesets.py tests/test_cli_apply_rulesets.py tests/test_cli_reconcile.py tests/core/test_settingsdrift.py tests/test_github_platform.py -q
        aviato validate

- [ ] **Step 7: Commit.**

        git add aviato/github.py aviato/rulesets.py aviato/cli.py aviato/core/ports.py aviato/github_platform.py docs/requirements/modules/onboarding/flow.md docs/requirements/modules/drift/settings-drift.md tests
        git commit -m "fix(rulesets): degrade only unsupported tag metadata rules"

---

### Task 14: Close workflow credential, reviewer, and durable-evidence gaps

**Files:**

- Modify: .github/workflows/reusable-consumer-automation.yml
- Modify: .github/workflows/reusable-release-gate.yml
- Modify: .github/workflows/reusable-app-store-connect.yml
- Modify: aviato/library/scaffold/files/wf-docs-*.yml
- Modify: aviato/library/pipelines.yaml
- Modify: templates/ (regenerated)
- Modify: docs/requirements/modules/deployment/apple/requirements.md
- Test: tests/test_workflow_guards.py
- Test: tests/test_pipeline_privileges.py

**Interfaces:**

- Every checkout that does not deliberately push has persist-credentials: false. The docs caller drops the now-inert actions: read grant.
- The App Store environment gate passes only if a required_reviewers rule has a reviewers array with length greater than zero.
- After a successful upload, a separate no-secret/no-consumer-code job with contents: write downloads the receipt, uploads it as a durable GitHub Release asset, and appends/updates an idempotent App Store receipt section in the release notes. The secret-bearing deploy job does not get contents: write.

- [ ] **Step 1: Add red global checkout tests.** Parse every workflow; allow persist-credentials:true only in the exact jobs that push a known ref. Specifically catch reusable-consumer-automation and reusable-release-gate.

- [ ] **Step 2: Add red App Store fixtures.** Missing protection_rules, missing reviewers, null reviewers, and an empty list fail; one real reviewer passes. The workflow shell/jq test must match aviato.github.protected_environment_has_reviewers.

- [ ] **Step 3: Add red durable-receipt tests.** Require the release-evidence job, minimal permissions, no secrets/checkout/build commands, idempotent release-note marker, receipt asset upload, and dependency on successful App Store upload.

- [ ] **Step 4: Run red tests.**

        python -m pytest tests/test_workflow_guards.py tests/test_pipeline_privileges.py -q -k "persist_credentials or reviewer or receipt"

- [ ] **Step 5: Implement hardening and update pipeline privileges.** Correct the stale reusable-consumer-automation header comment to acknowledge the optional settings-read token.

- [ ] **Step 6: Regenerate callers and run workflow/privilege validation.**

        python scripts/regen-templates.py
        python -m pytest tests/test_workflow_guards.py tests/test_pipeline_privileges.py tests/test_validation_negative.py -q
        aviato validate

- [ ] **Step 7: Commit.**

        git add .github/workflows aviato/library/scaffold/files aviato/library/pipelines.yaml templates docs/requirements/modules/deployment/apple/requirements.md tests
        git commit -m "fix(workflows): isolate credentials and persist deploy evidence"

---

### Task 15: Make doctor, fleet paths, onboarding plans, and slug validation honest

**Files:**

- Modify: aviato/core/diagnosis.py
- Modify: aviato/core/ports.py
- Modify: aviato/github_platform.py
- Modify: aviato/github.py
- Modify: aviato/cli.py
- Modify: README.md
- Test: tests/core/test_diagnosis.py
- Test: tests/core/test_fleet.py
- Modify: tests/test_cli_doctor.py
- Test: tests/test_cli_scan.py
- Test: tests/test_cli_drift_report.py
- Test: tests/test_cli_onboard.py
- Test: tests/test_cli_provision.py
- Test: tests/test_cli_apply_rulesets.py

**Interfaces:**

- DiagnosisReport exposes local drift_automation_present and remote drift_automation_enabled separately. Overall health is good only when both are true; unknown/disabled is broken, not silently replaced by local presence.
- _propose_file_drift and drift-report pass the same prerequisite_paths and drift_automation_markers as doctor/fleet scan.
- provision and apply-rulesets use the canonical is_owner_repo_slug validator. Reject whitespace, query/fragment text, option-shaped components, extra slashes, empty components, and control characters before any gh call.
- Onboard's dry-run plan lists each resolved protected deployment environment and says it must exist with at least one reviewer before deploy.

- [ ] **Step 1: Add red local-vs-remote health tests.** Cover local present/remote disabled, local missing/remote enabled, unknown, and both healthy. Doctor output must show both facts and exit consistently.

- [ ] **Step 2: Add red call-site parity tests.** Monkeypatch diagnose and assert doctor, fleet, scan --fix, and drift-report pass identical profile-derived prerequisite/automation data.

- [ ] **Step 3: Add red slug tests.** Parameterize a/b/c, a/b?x, a/b#x, leading/trailing whitespace, -a/b, a/-b, backslashes, newline, and empty components. Assert no clone/API helper is called.

- [ ] **Step 4: Add red onboarding-plan tests.** Python library lists pypi; GHCR profiles list ghcr; Swift lists app-store-connect; profiles without deploy environments print none.

- [ ] **Step 5: Run red tests.**

        python -m pytest tests/core/test_diagnosis.py tests/core/test_fleet.py tests/test_cli_doctor.py tests/test_cli_scan.py tests/test_cli_drift_report.py tests/test_cli_onboard.py tests/test_cli_provision.py tests/test_cli_apply_rulesets.py -q

- [ ] **Step 6: Implement shared helpers and update README examples.** Keep platform-specific probe keys outside core except for neutral report fields.

- [ ] **Step 7: Run the full CLI/fleet subsystem.**

        python -m pytest tests/core/test_fleet.py tests/test_cli_doctor.py tests/test_cli_scan.py tests/test_cli_drift_report.py tests/test_cli_onboard.py tests/test_cli_provision.py tests/test_cli_apply_rulesets.py -q
        aviato validate

- [ ] **Step 8: Commit.**

        git add aviato/core/diagnosis.py aviato/core/ports.py aviato/github_platform.py aviato/github.py aviato/cli.py README.md tests
        git commit -m "fix(doctor): report remote health and validate operator inputs"

---

### Task 16: Harden the local validation gate and packaging metadata

**Files:**

- Modify: scripts/validate.sh
- Modify: aviato/validation.py
- Modify: aviato/plugins/actionpins.py
- Modify: scripts/regen-templates.py
- Create: scripts/sync-docs-toolchain-pins.py
- Create: aviato/library/docs-toolchain.yaml
- Modify: website/requirements.txt
- Modify: starter/docs-site/requirements.txt
- Modify: aviato/library/scaffold/files/docs-requirements.txt.txt
- Modify: pyproject.toml
- Modify: .gitignore
- Test: tests/test_local_gate.py
- Test: tests/test_validation_negative.py
- Test: tests/core/test_actionpins.py
- Create: tests/test_docs_toolchain_parity.py

**Interfaces:**

- scripts/validate.sh detects the build distribution with importlib.metadata.version("build"), not import build, so a stale build/ output directory cannot shadow a missing tool.
- _check_monotonic_alias_parity uses a finite timeout and maps TimeoutExpired to one actionable validation error.
- Docs caller name parity covers authoritative scaffold bodies, regenerated templates, and rendered Library instances. Required parity source files being absent is an error, never a skip.
- Root pyproject optional dependency extras pass through unpinned_pyproject_extra_lines; the documented build-system/setuptools floor remains outside this exact-pin gate.
- aviato/library/docs-toolchain.yaml is the one source for exact Zensical/mike/pydoc-markdown pins; sync-docs-toolchain-pins.py rewrites the three requirements copies deterministically and --check is part of validation.
- scripts/regen-templates.py gains --check; it compares generated bytes without writing and exits nonzero with every drifted template path.
- Use SPDX license = "MIT" and license-files = ["LICENSE"]. Ignore .coverage.

- [ ] **Step 1: Add the red build-shadow integration test.** Run the non-strict gate with an empty build/ directory on PYTHONPATH and an interpreter environment without the build distribution. Assert the loud skipped-tool banner, not an attempted python -m build failure.

- [ ] **Step 2: Add red timeout, missing-source, rendered-name, root-pin, and docs-pin tests.** Monkeypatch the monotonic snippet to hang; remove a parity source; rename the rendered caller; float one root dev dependency; and change one generated docs pin. Each must produce one specific validation error.

- [ ] **Step 3: Run red tests.**

        python -m pytest tests/test_local_gate.py tests/test_validation_negative.py tests/core/test_actionpins.py tests/test_docs_toolchain_parity.py -q

- [ ] **Step 4: Implement finite/tool-safe detection and the pin generator.** The generator accepts no network input, preserves comments/order from its fixed templates, supports --check, and writes only the three declared outputs.

- [ ] **Step 5: Modernize package metadata and ignore coverage output.** Build with warnings visible and assert no SetuptoolsDeprecationWarning for license metadata.

- [ ] **Step 6: Run focused and full validation.**

        python scripts/sync-docs-toolchain-pins.py --check
        python -m pytest tests/test_local_gate.py tests/test_validation_negative.py tests/core/test_actionpins.py tests/test_docs_toolchain_parity.py -q
        AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh

- [ ] **Step 7: Commit.**

        git add scripts aviato/validation.py aviato/plugins/actionpins.py aviato/library/docs-toolchain.yaml aviato/library/scaffold/files/docs-requirements.txt.txt website/requirements.txt starter/docs-site/requirements.txt pyproject.toml .gitignore tests
        git commit -m "fix(validation): make local gates deterministic and fail closed"

---

### Task 17: Finish the active scaffold and profile contract cleanup

**Files:**

- Modify: aviato/library/policy.yml
- Modify: aviato/policy.py
- Modify: aviato/core/registry.py
- Modify: aviato/core/onboarding.py
- Modify: aviato/cli.py
- Modify: aviato/plugins/actionpins.py
- Modify: aviato/validation.py
- Modify: aviato/library/zizmor.yml
- Modify: .github/workflows/reusable-release.yml
- Modify: .github/workflows/reusable-consumer-automation.yml
- Modify: .github/workflows/reusable-common-lint.yml
- Modify: aviato/library/scaffold/files/contributing.md.txt
- Modify: aviato/library/scaffold/files/pyproject.toml.txt
- Modify: aviato/library/scaffold/files/ruff.toml.txt
- Modify: aviato/library/python-component.yaml
- Modify: aviato/library/scaffold/files/wf-python-component.yml
- Modify: templates/ (regenerated)
- Test: tests/core/test_onboarding.py
- Test: tests/core/test_dayzero_profiles.py
- Test: tests/core/test_actionpins.py
- Test: tests/core/test_zizmor_config.py
- Test: tests/test_validation_negative.py

**Interfaces:**

- Add library.repository: amattas/aviato to packaged policy data and expose library_repository(). Core rendering receives the repository value from Registry/policy data; no product slug literal remains in aviato/core.
- Validation binds the policy value to workflow install URLs, Zizmor policy, plug-in allowlist, generated uses references, contributing link, and the GitHub remote URL. Test fixtures may still name the example slug.
- Python consumer scaffold requires Python >=3.12 and Ruff target py312.
- python-component defines optional typecheck-command and passes it to reusable-python-ci exactly like python-library.

- [ ] **Step 1: Add the red repository-source test.** Change library.repository in a temporary policy tree and assert rendering, action-pin exemption, validation, and remote URL derive the new value. AST-scan aviato/core for the old literal.

- [ ] **Step 2: Add red Python scaffold tests.** Assert >=3.12, py312, and component custom typecheck command render/parity.

- [ ] **Step 3: Run red tests.**

        python -m pytest tests/core/test_onboarding.py tests/core/test_dayzero_profiles.py tests/core/test_actionpins.py tests/core/test_zizmor_config.py tests/test_validation_negative.py -q

- [ ] **Step 4: Implement policy-driven repository metadata.** Keep GitHub URL formatting in the binding layer; pass neutral strings into core rendering. Update every intentional literal and make validation enumerate all copies.

- [ ] **Step 5: Update Python scaffold/profile data and regenerate.**

        python scripts/regen-templates.py
        aviato sync .

- [ ] **Step 6: Run profile/scaffold/pin validation.**

        python -m pytest tests/core/test_onboarding.py tests/core/test_dayzero_profiles.py tests/core/test_actionpins.py tests/core/test_zizmor_config.py tests/test_validation_negative.py -q
        aviato validate

- [ ] **Step 7: Commit.**

        git add aviato .github/workflows/reusable-release.yml .github/workflows/reusable-consumer-automation.yml .github/workflows/reusable-common-lint.yml templates tests
        git commit -m "refactor(scaffold): centralize Library identity and finish profile parity"

---

### Task 18: Bring the entire test suite under strict typing

**Files:**

- Modify: tests/conftest.py
- Modify: tests/core/conftest.py
- Modify: tests/core/fakeplatform.py
- Modify: every test module in the fresh mypy inventory (34 files at audit baseline, including the shared fixtures/fake)
- Modify: pyproject.toml
- Modify: aviato/library/aviato-library.yaml
- Modify: .github/aviato.yaml
- Modify: .github/workflows/aviato-ci.yml (bootstrap sync)
- Test: tests/test_pipeline_privileges.py

**Baseline:** mypy --strict aviato tests currently reports 234 errors in 34 files. Largest groups are tests/test_github_platform.py (47), tests/test_cli_drift_report.py (34), tests/core/test_zizmor_scan.py (18), tests/test_command_hardening.py (15), tests/core/test_actionpins.py (14), tests/core/test_consent.py (12), and three 11-error modules.

**Interfaces:**

- The Library profile typecheck command becomes python -m mypy --strict aviato tests.
- Every Platform fake implements the real protocol signature and return type, including expected_live, revoke_consent, create_repo, and apply_settings -> list[str].
- Prefer typed fixture factories, Protocol-conforming fakes, Mapping/Sequence annotations, and cast at untyped library boundaries. Do not silence whole files, use ignore_missing_imports, or replace useful types with Any to reach zero.

- [ ] **Step 1: Capture a fresh error inventory after Tasks 1-17.**

        mypy --strict aviato tests 2>&1 | tee /tmp/aviato-mypy-tests.txt

  Expected before fixes: nonzero. Group by file and error code; commit no changes in this step.

- [ ] **Step 2: Fix shared fixtures and protocol fakes first.** Add explicit pytest fixture return types and Protocol signatures. Run:

        mypy --strict tests/conftest.py tests/core/conftest.py tests/core/fakeplatform.py tests/core/test_ports.py

- [ ] **Step 3: Fix the two largest binding/CLI groups.** Type tests/test_github_platform.py and tests/test_cli_drift_report.py, then run their tests plus mypy on those files.

- [ ] **Step 4: Fix parser/security groups.** Type tests/core/test_zizmor_scan.py, tests/test_command_hardening.py, tests/core/test_actionpins.py, tests/core/test_consent.py, tests/test_workflow_guards.py, tests/test_rulesets.py, and tests/test_cli_apply_rulesets.py. Run each affected pytest module.

- [ ] **Step 5: Fix the remaining modules from the fresh inventory.** Do not rely on the original 34-file list after earlier tasks add tests. The acceptance command is the whole tree, not a hand-maintained subset.

- [ ] **Step 6: Switch the source-of-truth typecheck command and bootstrap-sync.** Update pyproject/mypy invocation, aviato-library profile, and .github/aviato.yaml; then run aviato sync . if the caller render changes.

- [ ] **Step 7: Run strict typing and the full test suite.**

        mypy --strict aviato tests
        PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q

  Expected: zero mypy errors and all tests pass.

- [ ] **Step 8: Commit.**

        git add tests pyproject.toml aviato/library/aviato-library.yaml .github/aviato.yaml .github/workflows/aviato-ci.yml
        git commit -m "test(types): enforce strict typing across the suite"

---

### Task 19: Reconcile requirements, architecture, README, plans, and backlogs

**Files:**

- Modify: README.md
- Modify: SECURITY.md
- Modify: docs/architecture/infrastructure.md
- Modify: docs/architecture/validation.md
- Modify: docs/requirements/core/backlog.md
- Modify: docs/requirements/modules/deployment/apple/backlog.md
- Modify: docs/requirements/modules/deployment/docs-site/backlog.md
- Modify: docs/requirements/modules/deployment/ghcr/backlog.md
- Modify: docs/requirements/modules/deployment/pypi/backlog.md
- Modify: docs/requirements/modules/fleet/backlog.md
- Modify: docs/requirements/modules/languages/python/backlog.md
- Modify: docs/requirements/modules/onboarding/backlog.md
- Modify: docs/requirements/modules/scaffolding/backlog.md
- Modify: docs/requirements/modules/security/backlog.md
- Modify: docs/requirements/modules/starter-kit/backlog.md
- Modify: docs/requirements/modules/versioning/backlog.md
- Modify: docs/requirements/core/consumer-contract.md
- Modify: docs/requirements/modules/deployment/ghcr/requirements.md
- Modify: docs/requirements/modules/security/supply-chain.md
- Modify: docs/requirements/modules/versioning/release.md
- Modify: docs/superpowers/plans/2026-07-11-docs-restructure.md
- Modify: docs/superpowers/plans/2026-07-11-zensical-docs.md
- Test: tests/test_docs_index.py
- Test: tests/test_validation.py

**Interfaces:**

- README documents every load-bearing flag: --write, --migrate-profile, --allow-dirty, --var, --public, --override-version-pin, scan --fix/--audit, offboard --delete-files, --rebaseline-seeds, and serve-pages.
- Architecture/SECURITY describe the consumer-local PyPI publisher, same-run Pages deployment, explicit scan SHA, high/critical CodeQL enforcement, status bridge, profile identity, and degraded tag-rule posture.
- Add **STATUS: IMPLEMENTED** near the top of both completed 2026-07-11 plans. Do not mark this 2026-07-12 plan implemented until Task 20 is complete.
- Every resolved backlog item moves out of Open into a dated Resolved by 2026-07-12 hardening plan section. Keep only genuinely external/future work open.

- [ ] **Step 1: Correct normative contradictions in place.** Remove Dockerfile-seeding claims from §6.3/§13.2; reword the release diagram's UNCONDITIONALLY node; replace stale grep-mirror wording; make Pages source/workflow and PyPI identity text match Tasks 11-12.

- [ ] **Step 2: Clean stale backlog entries.** Mark the already-fixed owner autodetection and scaffold-constant parity items resolved. Remove the Swift manifest item because §12.3 explicitly records the opposite settled decision (Xcode project is operator-owned; no fragment is seeded). Remove contradictory Docusaurus/Algolia settled bullets. Correct stale wf-python-library.yml evidence paths.

- [ ] **Step 3: Disposition non-defects explicitly.** Keep numeric coverage threshold as opt-in/measure-only; keep secret-content heuristics out because the typed secret boundary is the deterministic contract; keep Zensical-native versioning as an external watch item until the feature exists. These must not appear as silently forgotten active defects.

- [ ] **Step 4: Update README, architecture, SECURITY, and old plan status headers.** Include exact operator commands for rulesets, Trusted Publisher workflow/environment, Pages build type, seed rebaseline, and live verification.

- [ ] **Step 5: Run documentation guards and stale-term scans.**

        python -m pytest tests/test_docs_index.py tests/test_validation.py -q
        rg -n "Docusaurus everywhere|Advance floating major reference UNCONDITIONALLY|no grep mirror|Deploy from a branch.*gh-pages|wf-python-library.yml" README.md SECURITY.md docs starter

  Expected: no stale normative hit; historical superpowers plans/specs may retain explicitly historical wording only when labeled as such.

- [ ] **Step 6: Commit.**

        git add README.md SECURITY.md docs starter/README.md tests/test_docs_index.py tests/test_validation.py
        git commit -m "docs: reconcile hardening requirements and backlog state"

---

### Task 20: Run the full local gate and prove each external control live

**Files:**

- Modify only if evidence exposes a defect: the owning implementation/test/docs from Tasks 1-19
- Evidence: GitHub run URLs, PR/check/status JSON, ruleset JSON, CodeQL alert query, TestPyPI/PyPI project URL, Pages deployment URL, App Store receipt release asset

**Interfaces:**

- Produces the final evidence bundle and the implemented status for this plan; it changes no product behavior unless a live check first reproduces a defect and the work returns to the owning earlier task.
- A live phase is complete only when the external service reports the exact expected ref/SHA, identity, status contexts, protection thresholds, deployment URL, or durable receipt named below.

**Operator checkpoints:** This task intentionally mutates external state. Pause before each numbered live phase, show the exact command/payload and affected repository/service, and obtain operator confirmation if execution was not already explicitly authorized.

- [ ] **Step 1: Verify the worktree is scoped.**

        git status --short
        git diff --check
        git diff --stat origin/main...HEAD

  Expected: only planned files; OVERLAY.md remains untracked and untouched; no .coverage/build/dist artifacts.

- [ ] **Step 2: Run fresh full local verification.**

        python scripts/regen-templates.py --check
        python scripts/sync-docs-toolchain-pins.py --check
        mypy --strict aviato tests
        PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --cov=aviato --cov-branch --cov-report=term-missing -q
        AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh
        aviato doctor . --no-remote-probe

  Expected: zero type errors, all tests pass, strict validation exits 0 with no skipped tools, package/wheel version parity passes, and local doctor has no broken artifact/integrity prerequisite.

- [ ] **Step 3: Open the implementation PR and verify check topology.** Confirm normal PR runs create real check runs; dispatch-only bridge does not run on an ordinary PR; CodeQL high/critical, dependency, secret, and common lint gates all appear. Do not merge on a partial/ambiguous result.

- [ ] **Step 4: Prove CodeQL blocking with a disposable canary PR.** Add a minimal known CodeQL test fixture on a disposable branch, confirm the workflow severity gate fails and the branch ruleset reports code-scanning failure, then close/delete the canary without merging. Run a clean analysis afterward and verify no open high/critical alert remains:

        gh api --paginate repos/amattas/aviato/code-scanning/alerts -f state=open -f tool_name=CodeQL --method GET

- [ ] **Step 5: Prove the release-status bridge before removing the bypass.** Let the release automation update/dispatch release PR 42. Query commit statuses and PR checks for its head SHA; require the exact ci, security, and common-lint contexts to be success. Only then proceed.

- [ ] **Step 6: Apply and inspect live protections.**

        aviato apply-rulesets amattas/aviato --apply --profile aviato-library
        gh api --paginate repos/amattas/aviato/rulesets

  Fetch each full ruleset. Require the branch ruleset to contain the CodeQL high-or-higher rule, required contexts, no bypass actors, deletion/non-fast-forward protection, and the PR rule. Require the tag ruleset to retain immutability; record the explicit degraded metadata-pattern warning if the plan still rejects that Enterprise-only rule. Enable Dependabot security updates and re-run live doctor:

        gh api --method PUT repos/amattas/aviato/automated-security-fixes
        aviato doctor .

- [ ] **Step 7: Prove consumer-local Trusted Publishing on TestPyPI.** In a disposable Python-library consumer, register .github/workflows/aviato-ci.yml plus environment pypi as the TestPyPI Trusted Publisher, cut a unique test version, and require build/audit/attestation/local publish/index-resolution success. Inspect the OIDC failure surface: no invalid-publisher and the consumer workflow identity is named. Do not use an API token fallback.

- [ ] **Step 8: Switch Aviato Pages to workflow mode and prove a release docs deployment.**

        gh api --method PUT repos/amattas/aviato/pages -f build_type=workflow

  Trigger the real release/docs path, require gh-pages to fast-forward, require deploy-pages success in the same run, and fetch the public site/version/latest alias. A green branch push without a Pages deployment is failure.

- [ ] **Step 9: Prove production release PR 42 end to end.** After TestPyPI proof and protected pypi environment review, merge through the normal gate. Require tag/release creation, exact wheel/runtime version parity, CodeQL release-ref success at the tagged SHA, PyPI Trusted Publishing, provenance/SBOM, resolvability, and docs deployment. Record URLs.

- [ ] **Step 10: Prove App Store evidence or record the external blocker.** On a real Swift consumer with valid App Store credentials, require a non-empty reviewer gate, successful upload, receipt asset on the GitHub Release, and idempotent receipt notes. If no authorized Apple project/credentials exist, leave this item explicitly blocked; do not claim the whole deployment program complete.

- [ ] **Step 11: Run the post-live audit.**

        aviato doctor .
        gh pr view 42 --json mergeable,mergeStateStatus,statusCheckRollup
        gh run list --limit 20
        git status --short

  Expected: live doctor reports CodeQL/Dependabot/Pages/drift health accurately; release PR is merged/closed after successful release; no interim bypass remains; local tree is clean except preserved OVERLAY.md.

- [ ] **Step 12: Mark this plan implemented and commit only the evidence links/status update.**

        git add docs/superpowers/plans/2026-07-12-repository-integrity-release-hardening.md
        git commit -m "docs: record repository hardening verification evidence"

## Final Acceptance Checklist

- [ ] No consumer-root operation can traverse a symlink or parent escape.
- [ ] Every declaration variable is typed, known, non-secret, and constraint-checked before rendering.
- [ ] Missing/corrupt seed state is visibly broken and cannot silently bless current content.
- [ ] Managed drift binds both body and resolved non-secret input identity; version-only moves do not churn.
- [ ] Profile re-pin compares a persisted stable identity and handles legacy declarations explicitly.
- [ ] Runtime, wheel, and project versions are identical.
- [ ] Security evidence names the exact analyzed ref/SHA; high/critical CodeQL blocks PR and release.
- [ ] Release workflow_run gating uses the tag commit; dispatch produces the exact required PR statuses.
- [ ] PyPI publishes from the consumer workflow identity with OIDC; Pages deploys through a same-run custom workflow.
- [ ] Ruleset fallback is limited to the known unsupported metadata rule and never hides degraded protection.
- [ ] Checkout credentials, App Store reviewers, and durable release evidence satisfy least privilege/fail-closed rules.
- [ ] Doctor/fleet output distinguishes local presence, remote enabled state, unknown, and degraded.
- [ ] Full tests are strict-typed; validation has finite subprocesses, non-shadowable tool probes, and complete parity checks.
- [ ] README, architecture, SECURITY, requirements, plan status, and backlogs agree with the implementation.
- [ ] Live GitHub, TestPyPI/PyPI, Pages, and (when authorized) App Store evidence is recorded; any unavailable external gate remains explicitly blocked.
