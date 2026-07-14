# Onboarding Readiness Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` to implement this plan task by task,
> with a specification-compliance review and a code-quality review after each
> task. Use `superpowers:systematic-debugging` for every unexpected failure and
> `superpowers:verification-before-completion` before any completion claim.

**Goal:** Close OR-001 through OR-021 with tested repository-controlled changes,
then prove OR-022 with the complete release-scoped five-profile evidence matrix
before declaring Aviato ready to onboard repositories.

**Architecture:** Build every consumer operation around one immutable pinned
`OperationContext`, compile one deterministic `DesiredState`, reconcile it
against a marker-derived managed inventory, and apply it through a journaled
transition executor. Build GitHub protection from that same state as a semantic,
confirmation-bound composite plan. Harden managed and starter release workflows
so unprivileged builders hand byte-identified artifacts to no-checkout privileged
publishers. Promote every durable contract and open blocker to the living
requirements, security, traceability, and runbook owners.

**Tech stack:** Python 3.12+, frozen dataclasses and typed enums, pytest, PyYAML,
Git and GitHub CLI, GitHub REST API, GitHub Actions, zizmor, yamllint, Ruff,
mypy, ShellCheck, TestPyPI/PyPI trusted publishing, GHCR/OCI, GitHub Pages,
App Store Connect/TestFlight.

## Global constraints

- Work only in
  `/Users/amattas/GitHub/aviato/.worktrees/onboarding-readiness-remediation` on
  `codex/onboarding-readiness-remediation`. The approved design commit
  `b55146e` must remain an ancestor. Do not touch the user's untracked
  `/Users/amattas/GitHub/aviato/OVERLAY.md` in the main checkout.
- The current approval authorizes local repository changes only. Read-only live
  inspection is permitted, but do not create or mutate any repository, branch,
  pull request, issue, workflow, setting, environment, ruleset, package, site,
  tag, release, or App Store object without the explicit checkpoint approval
  named in this plan.
- Before adding or changing mocks, read
  `superpowers:testing-anti-patterns`. Each behavior change starts with the named
  failing test, observes the expected failure for the intended reason, adds the
  smallest complete implementation, and reruns focused plus adjacent tests.
  Tests must assert state and behavior, not only mock calls.
- For every Task 2–24, the exact focused command printed in that task is a
  two-phase command: run it immediately after adding the named tests and before
  any production edit, require a nonzero RED result for the finding the task
  names, then rerun the identical selection after implementation and require a
  zero GREEN result. Record both outputs in the progress ledger. Never check an
  implementation checkbox before its RED result is observed.
- Prefer real temporary Git repositories, real generated YAML/JSON, and
  executable extraction of workflow script bodies. Mock only deterministic API,
  process-interruption, and response-loss boundaries.
- Use
  `PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH"` and
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` for repository tests. The final local gate is
  `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh`; a skipped required tool is a
  failure.
- Preserve the historical `0.3.0` release, its artifacts, and its failed
  post-publish confirmation as immutable regression evidence. Do not republish,
  retag, rerun, or rewrite it.
- Do not weaken the required `tag_name_pattern` contract or call the current
  unsupported-rule degradation equivalent protection. That state remains
  non-ready until the platform supports the rule or the user separately approves
  a requirement change.
- Never persist or print secrets, raw credentials, signing material,
  authenticated response bodies, or tokens. Durable evidence contains only
  identifiers, URLs, digests, conclusions, and redacted semantic state.
- Commit after each green task with the shown message. Do not combine unrelated
  tasks. Keep `.superpowers/sdd/progress.md` current after every task and review;
  do not commit it if the repository ignores it.
- Stage only the exact files declared by the current task; never use a
  directory-wide `git add` that could absorb concurrent user/reviewer work.
  Before every commit run `git diff --cached --name-only` and compare it to the
  task file list, then run `git diff --cached --check`.

## Wave 0: Establish a trustworthy baseline

### Task 1: Reconfirm the branch, tooling, tests, and drift-prone read-only state

**Files:**

- Verify: `docs/superpowers/specs/2026-07-14-onboarding-readiness-remediation-design.md`
- Verify: `pyproject.toml`
- Verify: `.github/aviato.yaml`
- Verify: `.yamllint.yml`
- Create/update locally if ignored: `.superpowers/sdd/progress.md`

- [ ] Confirm the isolated worktree and approved design ancestry:

```bash
cd /Users/amattas/GitHub/aviato/.worktrees/onboarding-readiness-remediation
git status --short --branch
git merge-base --is-ancestor b55146e HEAD
git diff --check
```

Expected: the branch is `codex/onboarding-readiness-remediation`, the design is
an ancestor, and there are no changes other than this committed plan when
implementation begins.

- [ ] Initialize the SDD progress ledger with all task names, current commit,
  exact worktree path, test command prefix, and the external-authorization
  boundary. Read `superpowers:testing-anti-patterns` before the first production
  test edit.
- [ ] Record, without mutating, the drift-prone Library state that later docs and
  evidence must reconcile:

```bash
gh pr view 59 --repo amattas/aviato --json number,state,isDraft,mergedAt,closedAt,url,statusCheckRollup
gh pr view 42 --repo amattas/aviato --json number,state,mergedAt,closedAt,url,statusCheckRollup
gh pr view 60 --repo amattas/aviato --json number,state,mergedAt,mergeCommit,url,statusCheckRollup
gh pr view 62 --repo amattas/aviato --json number,state,mergedAt,mergeCommit,url,statusCheckRollup
gh pr view 63 --repo amattas/aviato --json number,state,mergedAt,mergeCommit,url,statusCheckRollup
gh release view 0.3.0 --repo amattas/aviato --json tagName,isDraft,isPrerelease,publishedAt,url
gh api repos/amattas/aviato/automated-security-fixes --jq '{enabled,paused}'
gh api repos/amattas/aviato/environments --jq '.environments[] | {name,protection_rules}'
```

Expected: preserve the command responses in the task transcript, not a raw
credential-bearing repository file. Any changed state is recorded honestly and
does not trigger a mutation.

- [ ] Run the clean baseline and record the exact count rather than copying a
  historical count:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
python -m aviato.cli validate
```

Expected: both commands pass. Any failure stops feature work for systematic
diagnosis; do not bless a new baseline by editing the failing assertion.

No production commit is expected for this task. Commit only a deliberately
tracked progress-ledger change, if repository policy requires it.

## Wave 1: Pin one exact source and target

### Task 2: Resolve Library refs without ambiguous fallbacks

**Files:**

- Modify: `aviato/library_source.py`
- Modify: `aviato/github.py`
- Modify: `aviato/core/ports.py`
- Test: `tests/test_library_source.py`
- Test: `tests/test_github.py`

- [ ] Add failing tests named:

```text
test_accessible_repository_tag_404_may_fall_back_to_branch
test_tag_wins_when_tag_and_branch_share_a_name
test_hidden_or_ambiguous_404_never_falls_back_to_branch
test_auth_rate_limit_timeout_server_and_malformed_reads_are_errors
test_annotated_tag_peel_failure_never_falls_back_to_branch
test_ref_movement_after_resolution_still_fetches_original_commit_archive
test_archive_identity_must_match_the_resolved_commit
```

Use correlated fake GitHub responses for the API boundary and a real tar archive
for extraction. The current implementation must fail because `_read_object`
collapses operational failures into `None` and because the archive source is not
expressed as an immutable result object.

- [ ] Replace the optional tuple result with typed `FOUND`, `NOT_FOUND`, and
  `ERROR` outcomes and a `ResolvedLibraryRef` containing ref kind, requested pin,
  object SHA, peeled 40-character commit SHA, and repository identity. Establish
  repository accessibility/authentication before accepting an endpoint 404 as
  definite absence.
- [ ] Make tag resolution authoritative. Only a correlated tag `NOT_FOUND` may
  proceed to branch lookup; every other tag failure is terminal. Validate object
  kinds and recursively peel annotated tags without accepting cycles or
  malformed SHAs.
- [ ] Download the archive by the resolved commit SHA, validate the single archive
  root and Library layout, and expose the resolved kind/SHA for operator output.
  Move the ref between resolution and download in the test and prove byte
  identity still comes from the original SHA.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_library_source.py tests/test_github.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/library_source.py aviato/github.py aviato/core/ports.py tests/test_library_source.py tests/test_github.py
git commit -m "fix(source): resolve immutable library snapshots"
```

### Task 3: Introduce the canonical operation context and bootstrap snapshot

**Files:**

- Create: `aviato/core/operation_context.py`
- Modify: `aviato/core/bootstrap.py`
- Modify: `aviato/core/pathguard.py`
- Modify: `aviato/core/declaration.py`
- Modify: `aviato/core/fleet.py`
- Modify: `aviato/library_source.py`
- Modify: `aviato/cli.py`
- Modify: `docs/architecture/data-flow.md`
- Modify: `docs/specifications/core/consumer-contract.md`
- Modify: `docs/specifications/modules/onboarding/flow.md`
- Modify: `docs/specifications/modules/onboarding/bootstrap.md`
- Create: `tests/core/test_operation_context.py`
- Test: `tests/core/test_bootstrap.py`
- Test: `tests/test_cli_onboard.py`
- Test: `tests/test_cli_sync.py`
- Test: `tests/test_cli_doctor.py`
- Test: `tests/test_cli_provision.py`
- Test: `tests/test_cli_repin_offboard.py`
- Test: `tests/test_cli_reconcile.py`
- Test: `tests/test_cli_version_pin.py`
- Test: `tests/test_cli_apply_rulesets.py`
- Test: `tests/test_cli_scan.py`
- Test: `tests/test_cli_drift_report.py`
- Create: `tests/test_operation_context_boundaries.py`

- [ ] Add failing tests named:

```text
test_operation_context_owns_registry_policy_root_and_archive_lifetime
test_every_pin_bearing_command_uses_the_fetched_snapshot_not_installed_data
test_canonical_dot_tmp_alias_and_symlink_targets_resolve_before_any_write
test_nested_repository_directory_and_non_repository_target_are_rejected
test_bootstrap_snapshot_reads_operated_checkout_not_installed_package
test_bootstrap_snapshot_records_head_and_deterministic_library_tree_digest
test_reonboard_preserves_verified_bootstrap
test_bootstrap_is_rejected_outside_a_structural_library_before_render
test_consumer_modules_cannot_read_installed_source_or_policy_roots
```

Build installed and fetched fixture trees with visibly different templates,
rulesets, and policies. Parameterize the consumer commands (`onboard`, `sync`,
`doctor`, `repin`, `apply-rulesets`, `complete-protection`, `provision`,
`reconcile`, and pin-aware drift/version paths). The current commands must expose
their inconsistent `MODULE_SOURCE_ROOT`/`POLICY_DATA_ROOT` reads.

- [ ] Implement frozen `LibrarySnapshot` and `OperationContext` types. A
  published snapshot owns its temporary extraction lifetime, Registry, policy
  root, requested pin, resolved ref kind, commit SHA, and repository identity.
  Construct it exactly once and inject it through every pin-bearing path.
- [ ] Canonicalize the target once with `resolve()`, locate the Git root, and
  require equality. Handle macOS `/tmp`/`/private/tmp` aliases, symlinks, `.`,
  nonexistent targets, and nested paths before any declaration or artifact
  write.
- [ ] Permit bootstrap only for a structurally verified operated Library checkout.
  Read that checkout's `aviato/library` and policy tree, record Git HEAD and a
  stable tree digest, preserve an existing valid bootstrap flag on re-onboard,
  and reject bootstrap elsewhere before rendering.
- [ ] Remove post-context reads of installed source roots from consumer command
  bodies, including profile-check derivation, ruleset declaration mode, expected
  artifacts, onboard/proposal, doctor/fleet scan, sync, file/settings drift,
  repin/proposal, offboard/proposal, complete-protection, provision,
  bump-version, and reconcile. Installed roots remain usable only for validating
  Aviato's own installed/source package. Add an AST-based boundary test that
  rejects `MODULE_SOURCE_ROOT` or `POLICY_DATA_ROOT` in consumer paths.
- [ ] Update the consumer contract, onboarding/bootstrap behavior, and operation
  data-flow diagram in this same commit with canonical-root, pinned snapshot,
  exact ref outcome, and checkout-local bootstrap ownership.
- [ ] Run focused and cross-command verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q \
  tests/core/test_operation_context.py tests/core/test_bootstrap.py \
  tests/test_library_source.py tests/test_cli_onboard.py tests/test_cli_sync.py \
  tests/test_cli_doctor.py tests/test_cli_provision.py \
  tests/test_cli_repin_offboard.py tests/test_cli_reconcile.py \
  tests/test_cli_version_pin.py tests/test_cli_apply_rulesets.py \
  tests/test_cli_scan.py tests/test_cli_drift_report.py \
  tests/test_operation_context_boundaries.py tests/core/test_pathguard.py \
  tests/core/test_declaration.py tests/core/test_fleet.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/core/operation_context.py aviato/core/bootstrap.py aviato/core/pathguard.py aviato/core/declaration.py aviato/core/fleet.py aviato/library_source.py aviato/cli.py docs/architecture/data-flow.md docs/specifications/core/consumer-contract.md docs/specifications/modules/onboarding/flow.md docs/specifications/modules/onboarding/bootstrap.md tests/core/test_operation_context.py tests/core/test_bootstrap.py tests/core/test_pathguard.py tests/core/test_declaration.py tests/core/test_fleet.py tests/test_cli_onboard.py tests/test_cli_sync.py tests/test_cli_doctor.py tests/test_cli_provision.py tests/test_cli_repin_offboard.py tests/test_cli_reconcile.py tests/test_cli_version_pin.py tests/test_cli_apply_rulesets.py tests/test_cli_scan.py tests/test_cli_drift_report.py tests/test_operation_context_boundaries.py
git commit -m "refactor(core): bind operations to pinned context"
```

### Task 4: Close variable keys and add tri-state variable primitives

**Files:**

- Modify: `aviato/core/model.py`
- Modify: `aviato/core/variables.py`
- Modify: `aviato/core/onboarding.py`
- Modify: `aviato/cli.py`
- Test: `tests/core/test_variables.py`
- Test: `tests/core/test_onboarding.py`
- Test: `tests/test_cli_onboard.py`
- Test: `tests/test_cli_apply_rulesets.py`
- Test: `tests/test_cli_provision.py`

- [ ] Add failing tests named:

```text
test_unknown_flag_variable_is_rejected_before_preview_or_mutation
test_partial_resolution_coerces_supplied_values_and_marks_absent_values_unknown
test_partial_when_expression_is_true_false_or_indeterminate
test_exact_variable_resolution_still_requires_complete_typed_values
```

The current preview path must fail by silently dropping an unknown key, while
the primitive conditional evaluator must fail to represent an absent input.

- [ ] Add an explicit `Unknown` sentinel and typed partial-variable result.
  Validate supplied keys against the closed declaration set before merging any
  source, then reuse the existing coercion rules for supplied values.
- [ ] Make the reusable conditional evaluator tri-state (`true`, `false`, or
  indeterminate) without yet constructing a desired-state preview. Exact
  mutation-oriented variable resolution continues to require complete values.
- [ ] Thread the closed-set validation through CLI previews and all flag-accepting
  mutation/protection paths.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_variables.py tests/core/test_onboarding.py \
  tests/test_cli_onboard.py tests/test_cli_apply_rulesets.py tests/test_cli_provision.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/core/model.py aviato/core/variables.py aviato/core/onboarding.py aviato/cli.py tests/core/test_variables.py tests/core/test_onboarding.py tests/test_cli_onboard.py tests/test_cli_apply_rulesets.py tests/test_cli_provision.py
git commit -m "fix(variables): close keys and model unknown values"
```

## Wave 2: Compile one deterministic desired state

### Task 5: Add workflow envelopes, job fragments, and graph validation

**Files:**

- Modify: `aviato/core/model.py`
- Modify: `aviato/core/registry.py`
- Modify: `aviato/core/composition.py`
- Modify: `aviato/core/variables.py`
- Modify: `aviato/core/onboarding.py`
- Modify: `aviato/cli.py`
- Create: `aviato/core/compiler.py`
- Modify: `docs/requirements/core/structure.md`
- Modify: `docs/requirements/core/modularity.md`
- Modify: `docs/architecture/data-flow.md`
- Modify: `docs/requirements/modules/README.md`
- Modify: `docs/specifications/modules/onboarding/flow.md`
- Modify: `docs/specifications/modules/scaffolding/sync.md`
- Test: `tests/core/test_model.py`
- Test: `tests/core/test_registry.py`
- Test: `tests/core/test_composition.py`
- Create: `tests/core/test_compiler.py`
- Test: `tests/core/test_variables.py`
- Test: `tests/core/test_onboarding.py`
- Test: `tests/test_cli_onboard.py`

- [ ] Add failing tests named:

```text
test_registry_loads_data_only_workflow_envelopes_and_job_fragments
test_selected_pipeline_contributes_triggers_jobs_checks_and_artifacts
test_pipeline_removal_removes_its_jobs_triggers_checks_privileges_and_artifacts
test_scaffold_templates_are_base_union_selected_pipeline_artifacts
test_compiler_is_deterministic_for_equivalent_input_order
test_compiler_rejects_duplicate_jobs_paths_and_incompatible_triggers
test_compiler_rejects_missing_needs_and_pipeline_dependencies
test_compiler_rejects_orphaned_checks_permissions_inputs_secrets_and_environments
test_compiler_rejects_removal_of_an_always_on_pipeline
test_compiler_rejects_workflow_privilege_broader_than_selected_graph
test_legacy_workflow_schema_is_read_only_and_v2_is_required_for_graph_mutation
test_partial_preview_lists_definite_and_conditional_outputs
test_partial_preview_never_has_an_applicable_plan_id
test_exact_desired_state_requires_complete_typed_variables
```

Construct minimal registries in fixtures and assert parsed YAML behavior, not
only serialized strings. The current monolithic caller model must fail because
removing a pipeline changes `ResolvedSet.pipelines` without removing executable
jobs.

- [ ] Add frozen `WorkflowEnvelopeModule`, `WorkflowJobModule`, and expanded
  `PipelineModule` fields for stable identity, envelope, trigger contribution,
  fragment, required pipeline/job dependencies, referenced template artifacts,
  permissions, inputs, secrets, runner, environment, status check, and always-on
  status.
- [ ] Load only confined data references. Schema validation rejects unknown
  keys, absolute/traversing paths, duplicate identities, missing fragments,
  malformed YAML ASTs, and raw executable strings in module descriptors.
- [ ] Implement `DesiredState`, `PartialDesiredState`, and pure
  `compile_desired_state`/`compile_partial_desired_state`. Deep-merge trigger maps
  with explicit list add/remove semantics, topologically validate jobs, derive
  exact privilege/environment/check sets, and render one deterministic managed
  caller per nonempty envelope.
- [ ] Wire the Task 4 `Unknown`/tri-state primitives into partial compilation. A
  fresh read-only preview lists definite versus conditional artifacts, settings,
  environments, checks, and missing inputs; it never has an applicable plan ID
  or mutation path. Exact compilation requires complete typed variables.
- [ ] Resolve templates as the explicit union of scaffold-bundle templates and
  selected pipeline artifact references, retaining existing add/remove,
  condition, and output-collision rules.
- [ ] Model workflow schema version explicitly. Missing version means legacy v1;
  v1 snapshots may support read-only diagnosis/offboard and the source side of
  repin, but any graph-changing mutation must require v2 and print repin
  guidance. Do not add target-specific legacy workflow pruning to core.
- [ ] Update the living structure/modularity requirements, module index,
  architecture flow, onboarding compiler contract, and sync contract in this
  same commit; include the new module fields and pipeline-conditioned template
  resolution in their diagrams/tables.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_model.py tests/core/test_registry.py \
  tests/core/test_composition.py tests/core/test_compiler.py \
  tests/core/test_variables.py tests/core/test_onboarding.py \
  tests/test_cli_onboard.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/core/model.py aviato/core/registry.py aviato/core/composition.py aviato/core/variables.py aviato/core/onboarding.py aviato/core/compiler.py aviato/cli.py docs/requirements/core/structure.md docs/requirements/core/modularity.md docs/architecture/data-flow.md docs/requirements/modules/README.md docs/specifications/modules/onboarding/flow.md docs/specifications/modules/scaffolding/sync.md tests/core/test_model.py tests/core/test_registry.py tests/core/test_composition.py tests/core/test_compiler.py tests/core/test_variables.py tests/core/test_onboarding.py tests/test_cli_onboard.py
git commit -m "feat(core): compile pipeline-owned workflow graphs"
```

### Task 6: Migrate every profile caller to pipeline-owned generation

**Files:**

- Modify: `aviato/library/pipelines.yaml`
- Create: `aviato/library/workflow-envelopes.yaml`
- Create: `aviato/library/workflow-fragments/security-baseline.yml`
- Create: `aviato/library/workflow-fragments/common-lint.yml`
- Create: `aviato/library/workflow-fragments/release-gate.yml`
- Create: `aviato/library/workflow-fragments/release-status-bridge.yml`
- Create: `aviato/library/workflow-fragments/drift-automation.yml`
- Create: `aviato/library/workflow-fragments/python-verify.yml`
- Create: `aviato/library/workflow-fragments/node-verify.yml`
- Create: `aviato/library/workflow-fragments/swift-verify.yml`
- Create: `aviato/library/workflow-fragments/release-python.yml`
- Create: `aviato/library/workflow-fragments/release-node.yml`
- Create: `aviato/library/workflow-fragments/release-swift.yml`
- Create: `aviato/library/workflow-fragments/pypi-publish.yml`
- Create: `aviato/library/workflow-fragments/ghcr-publish.yml`
- Create: `aviato/library/workflow-fragments/app-store-connect.yml`
- Create: `aviato/library/workflow-fragments/docs-python-library.yml`
- Create: `aviato/library/workflow-fragments/docs-python-service.yml`
- Create: `aviato/library/workflow-fragments/docs-python-component.yml`
- Create: `aviato/library/workflow-fragments/docs-node-service.yml`
- Create: `aviato/library/workflow-fragments/docs-swift-app.yml`
- Modify: `aviato/library/{aviato-library,node-service,python-component,python-library,python-service,swift-app}.yaml`
- Modify: `aviato/library/bundles/workflows/{base,node-service-wf,python-component-wf,python-library-wf,python-service-wf,swift-app-wf}.yaml`
- Modify: `aviato/library/bundles/scaffold/{aviato-library-sc,node-service-sc,python-component-sc,python-library-sc,python-service-sc,swift-app-sc}.yaml`
- Delete: `aviato/library/scaffold/{wf-ci-node-service,wf-ci-python-component,wf-ci-python-library,wf-ci-python-service,wf-ci-swift-app}.yaml`
- Delete: `aviato/library/scaffold/{wf-docs-node-service,wf-docs-python-component,wf-docs-python-library,wf-docs-python-service,wf-docs-swift-app}.yaml`
- Delete: `aviato/library/scaffold/files/wf-{node-service,python-component,python-library,python-service,swift-app}.yml`
- Delete: `aviato/library/scaffold/files/wf-docs-{node-service,python-component,python-library,python-service,swift-app}.yml`
- Generated/verify: `.github/workflows/aviato-ci.yml`
- Generated/verify: `.github/workflows/aviato-drift.yml`
- Generated/verify: `templates/profile-{node-service,python-component,python-library,python-service,swift-app}.yml`
- Generated/verify: `templates/consumer-automation.yml`
- Modify: `scripts/regen-templates.py`
- Modify: `aviato/validation.py`
- Modify: `docs/architecture/infrastructure.md`
- Modify: `docs/specifications/modules/onboarding/flow.md`
- Modify: `docs/specifications/modules/scaffolding/sync.md`
- Test: `tests/core/test_dayzero_profiles.py`
- Test: `tests/core/test_onboarding.py`
- Test: `tests/test_pipeline_privileges.py`
- Test: `tests/test_workflow_guards.py`
- Test: `tests/test_validation_negative.py`

- [ ] Add failing behavioral tests named:

```text
test_all_five_profiles_compile_expected_envelopes_jobs_and_checks
test_removing_release_pipeline_removes_release_jobs_and_tag_trigger
test_removing_docs_pipeline_removes_docs_job_schedule_and_pages_privileges
test_removing_deploy_pipeline_removes_environment_and_artifact_owner
test_generated_callers_have_no_jobs_outside_selected_pipeline_graph
test_generated_permissions_equal_the_compiled_job_union
test_generated_checks_are_exactly_the_compiled_producers
test_generated_templates_are_byte_stable_after_second_regeneration
test_every_v2_profile_declares_workflow_schema_two
test_bootstrap_self_sync_generates_ci_drift_and_consumer_automation_parity
```

Include add/remove override fixtures for all five profiles and the docs opt-in.
Require semantic absence of jobs and triggers, rather than absence of a pipeline
name in metadata.

- [ ] Before changing Library data or regeneration code, run this RED selection:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_dayzero_profiles.py tests/core/test_onboarding.py \
  tests/test_pipeline_privileges.py tests/test_workflow_guards.py \
  tests/test_validation_negative.py
```

Expected: the new semantic removal/bootstrap-parity tests fail because callers
are still monolithic and the generator does not own both bootstrap workflows.

- [ ] Split the existing CI and docs caller bodies into shared envelopes plus
  pipeline-owned fragments. Add an explicit always-on drift-automation owner if
  needed so every executable managed workflow has one stable module owner.
  Retain reusable workflow pins and existing security/release semantics byte for
  byte unless the graph model requires a deterministic serialization change.
- [ ] Remove duplicate monolithic ownership descriptors only after every profile
  compiles to equivalent default behavior. Keep only data-driven references;
  do not add target-name conditionals to core Python.
- [ ] Mark all six production profiles as workflow schema v2. Preserve the Task 5
  v1 read-only compatibility boundary; defer v1-to-v2 migration execution to
  Task 9 after inventory and transitions exist.
- [ ] Update template regeneration and validation to compile from the graph.
  Validate status checks, permissions, secrets, inputs, runners, and environments
  against the rendered workflow AST. Extend the exact generator/check surface to
  own bootstrap `.github/workflows/aviato-ci.yml`,
  `.github/workflows/aviato-drift.yml`, all five profile templates, and
  `templates/consumer-automation.yml` from `.github/aviato.yaml`; do not stage an
  output that the named generator cannot reproduce.
- [ ] Update infrastructure plus onboarding/sync diagrams and tables in the same
  commit with the final envelope/job/trigger/artifact ownership and generator
  source-of-truth.
- [ ] Regenerate twice and prove parity:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" python scripts/regen-templates.py
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" python scripts/regen-templates.py --check
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_dayzero_profiles.py tests/core/test_onboarding.py \
  tests/test_pipeline_privileges.py tests/test_workflow_guards.py \
  tests/test_validation_negative.py
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" python -m aviato.cli validate
git diff --check
```

- [ ] Commit:

```bash
git add aviato/library/pipelines.yaml aviato/library/workflow-envelopes.yaml \
  aviato/library/workflow-fragments/security-baseline.yml \
  aviato/library/workflow-fragments/common-lint.yml \
  aviato/library/workflow-fragments/release-gate.yml \
  aviato/library/workflow-fragments/release-status-bridge.yml \
  aviato/library/workflow-fragments/drift-automation.yml \
  aviato/library/workflow-fragments/python-verify.yml \
  aviato/library/workflow-fragments/node-verify.yml \
  aviato/library/workflow-fragments/swift-verify.yml \
  aviato/library/workflow-fragments/release-python.yml \
  aviato/library/workflow-fragments/release-node.yml \
  aviato/library/workflow-fragments/release-swift.yml \
  aviato/library/workflow-fragments/pypi-publish.yml \
  aviato/library/workflow-fragments/ghcr-publish.yml \
  aviato/library/workflow-fragments/app-store-connect.yml \
  aviato/library/workflow-fragments/docs-python-library.yml \
  aviato/library/workflow-fragments/docs-python-service.yml \
  aviato/library/workflow-fragments/docs-python-component.yml \
  aviato/library/workflow-fragments/docs-node-service.yml \
  aviato/library/workflow-fragments/docs-swift-app.yml \
  aviato/library/aviato-library.yaml aviato/library/node-service.yaml \
  aviato/library/python-component.yaml aviato/library/python-library.yaml \
  aviato/library/python-service.yaml aviato/library/swift-app.yaml \
  aviato/library/bundles/workflows/base.yaml \
  aviato/library/bundles/workflows/node-service-wf.yaml \
  aviato/library/bundles/workflows/python-component-wf.yaml \
  aviato/library/bundles/workflows/python-library-wf.yaml \
  aviato/library/bundles/workflows/python-service-wf.yaml \
  aviato/library/bundles/workflows/swift-app-wf.yaml \
  aviato/library/bundles/scaffold/aviato-library-sc.yaml \
  aviato/library/bundles/scaffold/node-service-sc.yaml \
  aviato/library/bundles/scaffold/python-component-sc.yaml \
  aviato/library/bundles/scaffold/python-library-sc.yaml \
  aviato/library/bundles/scaffold/python-service-sc.yaml \
  aviato/library/bundles/scaffold/swift-app-sc.yaml \
  aviato/library/scaffold/wf-ci-node-service.yaml \
  aviato/library/scaffold/wf-ci-python-component.yaml \
  aviato/library/scaffold/wf-ci-python-library.yaml \
  aviato/library/scaffold/wf-ci-python-service.yaml \
  aviato/library/scaffold/wf-ci-swift-app.yaml \
  aviato/library/scaffold/wf-docs-node-service.yaml \
  aviato/library/scaffold/wf-docs-python-component.yaml \
  aviato/library/scaffold/wf-docs-python-library.yaml \
  aviato/library/scaffold/wf-docs-python-service.yaml \
  aviato/library/scaffold/wf-docs-swift-app.yaml \
  aviato/library/scaffold/files/wf-node-service.yml \
  aviato/library/scaffold/files/wf-python-component.yml \
  aviato/library/scaffold/files/wf-python-library.yml \
  aviato/library/scaffold/files/wf-python-service.yml \
  aviato/library/scaffold/files/wf-swift-app.yml \
  aviato/library/scaffold/files/wf-docs-node-service.yml \
  aviato/library/scaffold/files/wf-docs-python-component.yml \
  aviato/library/scaffold/files/wf-docs-python-library.yml \
  aviato/library/scaffold/files/wf-docs-python-service.yml \
  aviato/library/scaffold/files/wf-docs-swift-app.yml \
  aviato/validation.py scripts/regen-templates.py \
  .github/workflows/aviato-ci.yml .github/workflows/aviato-drift.yml \
  templates/consumer-automation.yml templates/profile-node-service.yml \
  templates/profile-python-component.yml templates/profile-python-library.yml \
  templates/profile-python-service.yml templates/profile-swift-app.yml \
  tests/core/test_dayzero_profiles.py tests/core/test_onboarding.py \
  tests/test_pipeline_privileges.py tests/test_workflow_guards.py \
  tests/test_validation_negative.py docs/architecture/infrastructure.md \
  docs/specifications/modules/onboarding/flow.md \
  docs/specifications/modules/scaffolding/sync.md
git commit -m "refactor(library): generate callers from pipeline graph"
```

## Wave 3: Reconcile and apply local state safely

### Task 7: Add the marker-derived managed inventory and universe scan

**Files:**

- Create: `aviato/core/inventory.py`
- Modify: `aviato/core/marker.py`
- Modify: `aviato/core/scaffold.py`
- Modify: `aviato/core/diagnosis.py`
- Modify: `aviato/repos.py`
- Modify: `docs/requirements/core/state-and-failures.md`
- Modify: `docs/specifications/core/consumer-contract.md`
- Modify: `docs/specifications/modules/scaffolding/sync.md`
- Create: `tests/core/test_inventory.py`
- Modify: `tests/core/test_scaffold.py`
- Modify: `tests/core/test_diagnosis.py`

- [ ] Add failing tests named:

```text
test_inventory_is_schema_versioned_marker_bearing_and_does_not_list_itself
test_marker_universe_scans_tracked_and_untracked_nonignored_git_files
test_marker_universe_excludes_git_metadata_build_roots_and_nested_worktrees
test_missing_truncated_malformed_modified_and_path_injecting_inventory_fail_closed
test_inventory_cannot_hide_a_marked_file_it_omits
test_unambiguous_legacy_marker_is_adopted_but_ambiguity_blocks
test_clean_obsolete_managed_artifact_is_retirable
test_dirty_foreign_malformed_symlinked_or_unreadable_obsolete_artifact_blocks
test_missing_obsolete_artifact_drops_from_next_inventory
test_seed_once_artifact_is_never_retired_by_managed_inventory
```

Use real temporary Git repositories and `git add`/untracked/ignored states. The
current implementation must fail to discover a stale marked workflow omitted
from the current desired templates.

- [ ] Implement schema-validated `ManagedInventory`, `InventoryEntry`, and
  `OwnedRulesetEntry` models for `.github/aviato.managed.yml`. Record profile
  identity, pin, snapshot commit, path-to-stable-artifact identity, pipeline
  owners, marker/body/input hashes, legacy aliases, and owned remote ruleset
  fingerprints. Render its own normal Aviato marker, validate its body separately,
  and exclude it from ordinary entries.
- [ ] Implement a confined Git marker-universe scan over tracked plus untracked
  nonignored files. Reconcile it with desired state and prior inventory every
  time; inventory is an index, while a valid live marker/body remains deletion
  authority.
- [ ] Classify expected, obsolete-clean, obsolete-missing, obsolete-blocked,
  legacy-adoptable, and ambiguous paths. Require current/source profile,
  recognized version, stable identity, and live body hash before retirement.
- [ ] Update the durable state, consumer-contract, and sync owners in this same
  commit with inventory-as-index/marker-as-authority, full marker-universe scan,
  legacy adoption, and safe-retirement rules.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_inventory.py tests/core/test_scaffold.py \
  tests/core/test_diagnosis.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/core/inventory.py aviato/core/marker.py aviato/core/scaffold.py aviato/core/diagnosis.py aviato/repos.py docs/requirements/core/state-and-failures.md docs/specifications/core/consumer-contract.md docs/specifications/modules/scaffolding/sync.md tests/core/test_inventory.py tests/core/test_scaffold.py tests/core/test_diagnosis.py
git commit -m "feat(core): track marker-derived managed inventory"
```

### Task 8: Plan and execute journaled, recoverable file transitions

**Files:**

- Create: `aviato/core/outcomes.py`
- Create: `aviato/core/transition.py`
- Modify: `aviato/core/scaffold.py`
- Modify: `aviato/core/onboarding.py`
- Modify: `aviato/core/offboarding.py`
- Modify: `aviato/command.py`
- Modify: `aviato/cli.py`
- Modify: `docs/architecture/data-flow.md`
- Modify: `docs/requirements/core/state-and-failures.md`
- Modify: `docs/specifications/modules/onboarding/flow.md`
- Modify: `docs/specifications/modules/scaffolding/sync.md`
- Create: `tests/core/test_transition.py`
- Modify: `tests/core/test_scaffold.py`
- Modify: `tests/core/test_onboarding.py`
- Modify: `tests/core/test_offboarding.py`
- Create: `tests/test_cli_recovery.py`
- Modify: `tests/test_command_hardening.py`

- [ ] Add failing tests named:

```text
test_transition_plan_is_pure_complete_deterministic_and_digest_bound
test_transition_conflict_preflight_performs_no_mutation
test_allow_dirty_never_allows_overlap_with_a_planned_path
test_executor_reconfines_and_refingerprints_every_path_before_mutation
test_executor_orders_managed_changes_then_sidecar_declaration_and_inventory_last
test_executor_preserves_mode_line_endings_and_atomic_replacement
test_ordinary_failure_rolls_back_preimages_and_verifies_semantics
test_interruption_at_each_operation_boundary_leaves_honest_recoverable_journal
test_same_plan_resumes_only_from_preimage_or_desired_fingerprint
test_different_plan_requires_explicit_rollback_or_recovery
test_recovery_refuses_path_matching_neither_preimage_nor_desired_state
test_success_requires_final_diagnosis_before_journal_removal
test_recovery_cli_inspects_then_requires_journal_id_to_resume_or_rollback
test_marker_scan_is_nul_safe_and_git_failures_map_to_aviato_error
test_same_worktree_transitions_are_serialized_by_nofollow_exclusive_lock
test_sigkill_at_every_wal_phase_is_recoverable_or_honestly_conflicted
test_parent_directory_swap_cannot_redirect_write_or_delete_outside_root
```

Parameterize fault injection across every write, deletion, sidecar, declaration,
inventory, journal-record, and cleanup boundary. Assert final filesystem state,
journal content, and structured completed/failed/indeterminate/unattempted
outcomes—not merely raised exceptions.

- [ ] Add shared `OperationStatus` and `OperationResult`. Model
  `TransitionPlan` with canonical root, snapshot SHA, declaration identity,
  plan digest, full replacement bytes and modes, clean deletions, seed additions,
  metadata updates, expected fingerprints, conflicts/notices, and deterministic
  order.
- [ ] Store the private journal and staged preimages under the absolute per-worktree
  Git administrative path resolved by `git rev-parse --path-format=absolute
  --git-dir`/`--git-path`, never a tracked consumer path. Namespace by worktree
  identity so sibling worktrees cannot collide. Use NUL-delimited Git path
  output. Record an operation durably before advancing; re-confine and
  re-fingerprint immediately before it.
- [ ] Acquire a non-following exclusive execution/recovery lock keyed to canonical
  repository plus worktree identity before the final validation and hold it
  through inventory acceptance and journal cleanup. Resume and rollback acquire
  the same lock. Fail closed on a live lock; validate ownership/process identity
  before explicitly recovering a stale lock. Prove two subprocesses cannot
  interleave different plans.
- [ ] Make the journal a crash-consistent write-ahead log. For each operation:
  securely write/hash/fsync its preimage, write and fsync a `PREPARED` intent,
  mutate with an atomic same-directory operation, fsync the target parent,
  append/fsync `APPLIED`, then advance. Fsync journal-directory creation,
  replacement, and deletion; validate backup hashes/schema during recovery.
  Send real subprocess `SIGKILL` at every durability boundary, not only injected
  Python exceptions.
- [ ] Eliminate parent-symlink TOCTOU by opening canonical root and each parent
  component with no-follow directory semantics, verifying inode/type, and using
  dirfd-relative temp creation/rename/unlink in the verified parent. Recovery
  uses the same primitive and never falls back to a pathname-only write.
- [ ] Roll back ordinary exceptions and verify restoration. Preserve interruption
  state for explicit resume/rollback, require an identical plan, and block any
  path that matches neither recorded preimage nor desired fingerprint. Add
  `aviato recover-transition PATH` for read-only inspection and require exactly
  one of `--resume` or `--rollback` plus `--confirm JOURNAL_ID` for mutation.
  Ordinary mutation commands refuse a pending journal and direct the operator to
  recovery. Accept the marker-bearing inventory only after a local convergence
  check—including its own marker/body—proves desired state; do not invoke public
  remote-probing `doctor` from the executor.
- [ ] Update the data-flow, state/failure, onboarding, and sync owners in this
  same commit with plan purity, lock/WAL phases, operation order, recovery
  commands, and honest partial-state semantics.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_transition.py tests/core/test_scaffold.py \
  tests/core/test_onboarding.py tests/core/test_offboarding.py \
  tests/test_cli_recovery.py tests/test_command_hardening.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/core/outcomes.py aviato/core/transition.py aviato/core/scaffold.py aviato/core/onboarding.py aviato/core/offboarding.py aviato/command.py aviato/cli.py docs/architecture/data-flow.md docs/requirements/core/state-and-failures.md docs/specifications/modules/onboarding/flow.md docs/specifications/modules/scaffolding/sync.md tests/core/test_transition.py tests/core/test_scaffold.py tests/core/test_onboarding.py tests/core/test_offboarding.py tests/test_cli_recovery.py tests/test_command_hardening.py
git commit -m "feat(core): apply recoverable repository transitions"
```

### Task 9: Route onboard, proposal, sync, and repin through one transition

**Files:**

- Modify: `aviato/cli.py`
- Modify: `aviato/github_platform.py`
- Modify: `aviato/core/transition.py`
- Modify: `aviato/core/onboarding.py`
- Modify: `aviato/core/offboarding.py`
- Modify: `docs/specifications/modules/onboarding/flow.md`
- Modify: `docs/specifications/modules/versioning/repin.md`
- Modify: `docs/specifications/modules/offboarding/flow.md`
- Modify: `tests/test_cli_onboard.py`
- Modify: `tests/test_cli_onboard_write.py`
- Modify: `tests/test_cli_onboard_proposal.py`
- Modify: `tests/test_cli_sync.py`
- Modify: `tests/test_cli_repin_offboard.py`
- Modify: `tests/test_cli_provision.py`
- Modify: `tests/test_github_platform.py`

- [ ] Add failing tests named:

```text
test_local_and_proposal_onboarding_execute_the_same_transition
test_fresh_proposal_includes_seed_sidecar_declaration_and_inventory
test_existing_seed_proposal_preserves_and_enumerates_seed_once_files
test_proposal_includes_clean_obsolete_deletions
test_unmanaged_dirty_foreign_and_malformed_collisions_block_before_proposal
test_local_collision_cannot_write_declaration_then_return_success
test_sync_and_repin_retire_only_clean_prior_snapshot_artifacts
test_profile_migration_carries_old_and_new_snapshots_for_retirement
test_post_merge_sync_is_idempotent_with_no_stale_workflow
test_interrupted_transition_makes_each_command_print_recovery_instructions
test_provision_clone_scaffold_uses_same_sidecar_inventory_and_preflight
test_offboard_preflights_complete_removal_and_cannot_leave_half_state
test_v1_to_v2_repin_adopts_only_unambiguous_legacy_aliases
```

Use a real bare remote plus clone for proposal tests. Inspect the actual proposal
branch diff, including `.github/aviato.seed.json` and
`.github/aviato.managed.yml`; do not reduce the test to an API call assertion.

- [ ] Replace manual local write loops and proposal `files` dictionaries with
  `plan_transition` plus `execute_transition`. Proposal mode clones first,
  executes the identical plan in that clone, verifies diagnosis, and gives the
  resulting worktree diff to the proposal creator.
- [ ] Enumerate preserved seed-once files and blocking collisions in output.
  Never create a partial-adoption PR. Make success conditional on complete
  desired-state convergence, with nonzero exit for conflicts or recovery state.
- [ ] Carry both source and target pinned snapshots for repin/profile migration so
  prior stable identities remain discoverable without trusting the installed
  Library. For v1-to-v2 repin, combine the v1 source snapshot with the marker
  universe, preserve the old seed sidecar, adopt only clean unambiguous legacy
  aliases, block dirty/ambiguous legacy state, and write the v2 managed inventory
  last. Floating prior pins use the inventory's recorded immutable snapshot SHA.
- [ ] Route provision's clone/scaffold phase through the same transition so fresh
  repositories receive identical seed and inventory state. Route offboard and
  offboard proposal through a complete empty/retained desired-state transition,
  or prove an equally complete preflight/executor contract; no half-offboarded
  state may report success.
- [ ] Update living onboarding (including its safer-ordering diagram), repin, and
  offboarding specifications in this same commit with shared preflight/executor,
  proposal-clone parity, v1-to-v2 migration, and complete failure semantics.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_cli_onboard.py tests/test_cli_onboard_write.py \
  tests/test_cli_onboard_proposal.py tests/test_cli_sync.py \
  tests/test_cli_repin_offboard.py tests/test_cli_provision.py \
  tests/test_github_platform.py \
  tests/core/test_transition.py tests/core/test_inventory.py \
  tests/core/test_onboarding.py tests/core/test_offboarding.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/cli.py aviato/github_platform.py aviato/core/transition.py aviato/core/onboarding.py aviato/core/offboarding.py docs/specifications/modules/onboarding/flow.md docs/specifications/modules/versioning/repin.md docs/specifications/modules/offboarding/flow.md tests/test_cli_onboard.py tests/test_cli_onboard_write.py tests/test_cli_onboard_proposal.py tests/test_cli_sync.py tests/test_cli_repin_offboard.py tests/test_cli_provision.py tests/test_github_platform.py
git commit -m "fix(onboard): converge local and proposal transitions"
```

## Wave 4: Bind remote protection to semantic plans

### Task 10: Build confirmation-bound semantic ruleset plans

**Files:**

- Create: `aviato/core/ruleset_plan.py`
- Modify: `aviato/core/outcomes.py`
- Modify: `aviato/core/ports.py`
- Modify: `aviato/core/inventory.py`
- Modify: `aviato/rulesets.py`
- Modify: `aviato/github.py`
- Modify: `aviato/github_platform.py`
- Modify: `aviato/cli.py`
- Modify: `docs/specifications/modules/drift/settings-drift.md`
- Modify: `docs/specifications/modules/reconcile/flow.md`
- Modify: `docs/security/controls.md`
- Create: `tests/core/test_ruleset_plan.py`
- Modify: `tests/test_rulesets.py`
- Modify: `tests/test_github.py`
- Modify: `tests/test_github_platform.py`
- Modify: `tests/test_cli_apply_rulesets.py`

- [ ] Add failing tests named:

```text
test_ruleset_plan_binds_repo_id_slug_default_branch_pin_snapshot_and_live_ids
test_ruleset_plan_id_is_stable_and_ignores_only_display_metadata
test_every_security_relevant_field_changes_the_plan_id
test_duplicate_desired_or_live_name_target_identity_fails_closed
test_plan_fetches_full_detail_for_every_paginated_ruleset_summary
test_condition_sets_normalize_default_branch_and_target_appropriate_all
test_condition_bytes_case_unknown_keys_and_malformed_shapes_never_false_green
test_declaration_mode_derives_github_slug_and_rejects_mismatch_or_non_github_remote
test_apply_requires_exact_recomputed_confirmation_and_one_repository
test_apply_rejects_changed_repo_branch_pin_snapshot_ruleset_id_or_before_payload
test_owned_ruleset_delete_requires_inventory_prior_render_live_match_and_receipt
test_unsafe_ruleset_delete_is_reported_manual_without_mutation
test_indeterminate_condition_comparison_cannot_apply
```

Assert canonical plan JSON, field-level changes, plan digest, and absence of API
writes for every refusal. Keep fleet/profile multi-repository preview if useful,
but emit one plan ID per repository and reject multi-repository apply.

- [ ] Add `RuleComparison`, `RulesetIdentity`, `RulesetChange`,
  `RulesetOperation`, `RepositoryIdentity`, and `RulesetPlan` frozen types.
  Canonical security data includes immutable repository ID/node ID, slug, default
  branch, tool version, declaration pin, snapshot SHA, selected live IDs,
  enforcement, normalized conditions, bypass actors, all rules and parameters,
  before fingerprints, actions, and desired payloads. Exclude only timestamps,
  URLs, and display objects.
- [ ] Fetch paginated summaries then full details. Key desired and live state by
  `(name, target)` and fail on duplicates. Normalize `ref_name.include/exclude`
  as sorted/deduped string sets, resolve only documented `~DEFAULT_BRANCH` and
  target-appropriate `~ALL`, preserve pattern bytes/case, and return
  indeterminate for unknown or malformed state.
- [ ] Make preview the default and print semantic before/after changes plus plan
  ID. `--apply` requires one repository and `--confirm <plan-id>`, reconstructs
  the pinned context and complete plan, then refuses any changed binding or
  indeterminate comparison. The Task 11 executor rechecks the whole plan and the
  selected live ID/fingerprint immediately before every sequential write.
- [ ] Permit deletion only when valid prior inventory owns the exact remote
  identity, its recorded snapshot reproduces the prior desired fingerprint, live
  state still matches, and the Consumer tracking issue contains the Task 11
  signature-verified, unedited, trusted-admin receipt binding repository,
  ruleset, plan, payload, comment/event, and signer IDs. Otherwise label it
  manual.
- [ ] Update settings-drift, reconcile, and security-control owners in this same
  commit with full-detail reads, condition normalization, confirmation binding,
  per-write recheck, receipt-gated retirement, and indeterminate semantics.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_ruleset_plan.py tests/test_rulesets.py \
  tests/test_github.py tests/test_github_platform.py tests/test_cli_apply_rulesets.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/core/ruleset_plan.py aviato/core/outcomes.py aviato/core/ports.py aviato/core/inventory.py aviato/rulesets.py aviato/github.py aviato/github_platform.py aviato/cli.py docs/specifications/modules/drift/settings-drift.md docs/specifications/modules/reconcile/flow.md docs/security/controls.md tests/core/test_ruleset_plan.py tests/test_rulesets.py tests/test_github.py tests/test_github_platform.py tests/test_cli_apply_rulesets.py
git commit -m "feat(rulesets): bind semantic plans to confirmation"
```

### Task 11: Unify provision and complete-protection on one composite plan

**Files:**

- Create: `aviato/core/protection.py`
- Create: `aviato/core/release_authorization.py`
- Modify: `aviato/core/model.py`
- Modify: `aviato/core/composition.py`
- Modify: `aviato/core/compiler.py`
- Modify: `aviato/core/provision.py`
- Modify: `aviato/core/ports.py`
- Modify: `aviato/core/ruleset_plan.py`
- Modify: `aviato/github.py`
- Modify: `aviato/github_platform.py`
- Modify: `aviato/cli.py`
- Create: `aviato/library/scaffold/wf-protection-checkpoint.yaml`
- Create: `aviato/library/scaffold/files/wf-protection-checkpoint.yml`
- Modify: `aviato/library/pipelines.yaml`
- Modify: `aviato/library/workflow-envelopes.yaml`
- Modify: `aviato/library/workflow-fragments/release-gate.yml`
- Modify: `aviato/library/workflow-fragments/release-python.yml`
- Modify: `aviato/library/workflow-fragments/release-node.yml`
- Modify: `aviato/library/workflow-fragments/release-swift.yml`
- Modify: `aviato/library/workflow-fragments/pypi-publish.yml`
- Modify: `aviato/library/workflow-fragments/ghcr-publish.yml`
- Modify: `aviato/library/workflow-fragments/app-store-connect.yml`
- Modify: `aviato/library/workflow-fragments/docs-python-library.yml`
- Modify: `aviato/library/workflow-fragments/docs-python-service.yml`
- Modify: `aviato/library/workflow-fragments/docs-python-component.yml`
- Modify: `aviato/library/workflow-fragments/docs-node-service.yml`
- Modify: `aviato/library/workflow-fragments/docs-swift-app.yml`
- Modify: `aviato/library/bundles/workflows/base.yaml`
- Modify: `.github/workflows/reusable-release-gate.yml`
- Modify: `.github/workflows/reusable-release.yml`
- Generated/verify: `.github/workflows/aviato-ci.yml`
- Generated/verify: `.github/workflows/aviato-protection-checkpoint.yml`
- Create: `templates/consumer-protection-checkpoint.yml`
- Generated/verify: `templates/profile-node-service.yml`
- Generated/verify: `templates/profile-python-component.yml`
- Generated/verify: `templates/profile-python-library.yml`
- Generated/verify: `templates/profile-python-service.yml`
- Generated/verify: `templates/profile-swift-app.yml`
- Modify: `scripts/regen-templates.py`
- Modify: `aviato/validation.py`
- Modify: `docs/architecture/infrastructure.md`
- Modify: `docs/architecture/security.md`
- Modify: `docs/specifications/modules/onboarding/flow.md`
- Modify: `docs/specifications/modules/reconcile/flow.md`
- Create: `tests/core/test_protection.py`
- Create: `tests/core/test_release_authorization.py`
- Modify: `tests/core/test_composition.py`
- Modify: `tests/core/test_compiler.py`
- Modify: `tests/core/test_dayzero_profiles.py`
- Modify: `tests/core/test_onboarding.py`
- Modify: `tests/core/test_provision.py`
- Modify: `tests/test_cli_provision.py`
- Modify: `tests/test_cli_apply_rulesets.py`
- Modify: `tests/test_github_platform.py`
- Modify: `tests/test_pipeline_privileges.py`
- Modify: `tests/test_workflow_guards.py`
- Modify: `tests/test_cli_release.py`
- Modify: `tests/test_validation_negative.py`

- [ ] Add failing tests named:

```text
test_protection_plan_contains_classic_security_merge_ruleset_environment_and_checks
test_protection_plan_binds_same_pinned_desired_state_as_transition
test_complete_protection_defaults_to_dry_run_and_requires_exact_confirm
test_complete_protection_applies_every_surface_not_settings_only
test_provision_is_not_full_when_rulesets_fail_after_settings_succeed
test_known_tag_pattern_degradation_is_visible_and_non_ready
test_full_noop_rerun_is_idempotent_only_after_fresh_binding
test_changed_repository_identity_default_branch_snapshot_or_live_state_refuses_apply
test_each_write_has_full_semantic_readback
test_lost_response_is_completed_only_when_readback_proves_desired_state
test_unreadable_post_write_state_is_indeterminate_and_never_blindly_retried
test_later_operations_are_unattempted_after_failure_or_indeterminate_result
test_unknown_environment_reviewer_identity_is_unattempted_and_non_ready
test_final_convergence_barrier_catches_earlier_or_post_last_write_drift
test_degraded_tag_fallback_requires_bound_payload_and_explicit_consent
test_protection_receipt_is_attached_with_ruleset_ids_and_payload_fingerprints
test_receipt_comment_failure_preserves_local_truth_and_blocks_auto_retirement
test_explicit_environment_reviewers_and_ref_policy_apply_and_read_back
test_environment_api_fields_wait_and_custom_rules_are_plan_bound
test_read_only_environment_admin_bypass_requires_false_or_manual_blocker
test_admin_bypass_false_and_independent_authorization_guard_are_both_required
test_signed_receipt_rejects_forgery_edit_untrusted_author_or_revoked_key
test_managed_checkpoint_collect_and_distinct_reviewer_sign_share_no_credentials
test_managed_checkpoint_binds_repo_tag_sha_actor_reviewer_submitter_and_protection
test_managed_checkpoint_intake_is_default_branch_no_secret_and_injection_safe
test_managed_checkpoint_intake_attestation_job_sees_only_verified_fixed_artifact
test_managed_checkpoint_template_is_generator_owned_and_byte_stable
test_checkpoint_workflow_is_generated_for_all_six_profiles_and_self_bootstrap
test_self_bootstrap_caller_has_generator_owned_closed_promotion_mode
test_privileged_jobs_compile_exact_managed_authorization_guard_descriptor
test_privileged_job_without_guard_is_graph_invalid_and_non_ready
test_managed_release_gate_verifies_one_exact_fresh_checkpoint_and_actual_actor
test_every_managed_privileged_job_rechecks_checkpoint_before_privilege
test_release_proposal_merge_stops_before_tag_floating_tag_and_github_release
test_promotion_dispatch_binds_exact_merged_sha_tag_actor_and_checkpoint_digest
test_missing_stale_or_mismatched_checkpoint_blocks_all_release_mutations
test_promotion_dispatch_uses_trusted_default_branch_code_and_no_consumer_checkout
test_team_only_reviewer_forged_membership_and_missing_checkpoint_are_non_ready
```

Use a deterministic fake platform whose state can change before every surface
and which can lose a response after accepting a write. Assert structured receipt
status and actual final semantic state.

- [ ] Implement frozen `ProtectionPlan` and `ProtectionReceipt`. Derive classic
  branch protection, repository/security/merge settings, full named rulesets,
  protected environments, and expected checks from the same pinned
  `DesiredState`. Hash all immutable target and before-state bindings into one
  confirmation ID.
- [ ] Represent protected environments with normalized concrete reviewer
  user/team identities, minimum count, self-review prevention, deployment
  branch/tag policy, wait timer, and custom protection rules. Bind
  every documented writable API field plus the live GET response's read-only
  `can_admins_bypass` field to the plan ID, per-write readback, and final
  convergence barrier. GitHub exposes that field for machine readback but does
  not expose it in the documented update schema, so never send a guessed write.
  Every privileged environment requires `can_admins_bypass == false`; when true
  or absent, emit a named manual-UI prerequisite and remain non-ready until a
  separately approved operator action disables it and a freshly recomputed plan
  reads back false. The preview-only `--forbid-admin-bypass` input binds this
  expected assertion but never attempts an undocumented mutation. The native
  environment gate and an independent, machine-verified authorization guard are
  both required; neither substitutes for the other. Bind that guard to trusted
  workflow path/blob, allowed event/ref/SHA, distinct current
  reviewer signature policy, and receipt schema/trust-policy digest. Model that
  guard descriptor in `DesiredState` and the protection plan; verify the rendered
  workflow implements it before reporting the environment ready. Add
  preview-bound repeatable CLI/provision inputs
  `--environment-reviewer user:LOGIN|team:ORG/SLUG`,
  `--environment-branch PATTERN`, `--environment-tag PATTERN`,
  `--environment-wait-minutes N`, `--prevent-self-review`, and
  `--forbid-admin-bypass`. Resolve logins/team slugs and deployment refs to
  immutable IDs before confirmation. A fresh environment has a positive
  convergence path only with those explicit inputs plus the manual false
  readback; never invent identities. Missing or
  unreadable documented fields are `unattempted`/non-ready, and an explicitly
  required but API-unverifiable policy is a named retained blocker rather than a
  fabricated green field.
- [ ] Implement the reusable managed authorization guard rather than leaving the
  Task 6 graph contract abstract. `ManagedReleaseCheckpoint` is a versioned
  canonical schema/trust policy binding repository ID/slug, tag/SHA, intended
  release actor, collector, exact concrete user reviewer, separately identified
  workflow submitter, desired snapshot/pin, protection plan/receipt, full
  ruleset/CodeQL/environment/check fingerprints including exact
  `can_admins_bypass == false`, trusted workflow path/blob, and short expiry.
  `aviato release-checkpoint collect` performs the privileged
  readback only on the administrator/operator's machine using the current `gh`
  credential and emits unsigned redacted bytes; `review-sign` runs without that
  credential on the distinct configured user reviewer's machine and SSH-signs
  the exact bytes. Never share the reviewer private key or operator token, never
  accept a self-asserted team-membership claim, and never persist raw responses.
- [ ] Generate a consumer-local `.github/workflows/aviato-protection-checkpoint.yml`
  from the new scaffold/template for all six production profiles, including the
  `aviato-library` self-bootstrap output at that exact root path. It is a
  `workflow_dispatch`-only, current-default-branch, no-checkout, no-environment,
  no-secret intake. Workflow permissions default to `{}`. Its `contents: read`
  verifier job accepts bounded base64url data only through environment variables
  into resource-bounded inline Python, verifies repository/workflow/ref/run,
  current concrete reviewer key, signed receipt, intended actor, and bound
  submitter, and uploads one fixed verified artifact. A separate job with exactly
  `contents: read`, `id-token: write`, and `attestations: write` sees only that
  artifact and emits the offline-verifiable bundle. Pin all actions by SHA and
  prove multiline/expression/path inputs cannot become code or filenames.
- [ ] Make the managed release-gate fragment locate exactly one unexpired intake
  run for its tag/SHA, verify the bundle offline plus reviewer signature/current
  key, require actual release actor to equal the signed intended actor and differ
  from the signer, and bind the checkpoint digest into every downstream artifact
  manifest. Before each environment secret, OIDC request, or hosted mutation,
  re-read the supported environment/protection fields and revalidate the same
  checkpoint/digest. All PyPI, GHCR, Pages, App Store, and GitHub Release managed
  jobs use this implementation. Missing/ambiguous/stale state, a team-only
  reviewer, unavailable attestation capability, or any signer/actor/workflow/
  fingerprint mismatch is non-ready before privilege.
- [ ] Split managed release proposal from promotion. A normal default-branch push
  and the push caused by merging the release proposal may compute/version/open
  the proposal, but `reusable-release.yml` must stop before creating the release
  tag, floating-major tag, or GitHub Release. Extend every generated managed
  caller's trusted-default-branch `workflow_dispatch` with a closed promotion
  mode carrying exact merged SHA, intended tag, intended actor, checkpoint run
  ID, and checkpoint digest. Only that mode may call the mutation phase, and it
  first verifies current default-branch reachability, absent-or-correlated remote
  tag/release state, actual actor equality, the fresh managed checkpoint, every
  derived privileged environment, and exact-SHA CI/security. It performs no
  consumer checkout or helper execution. Missing/stale/mismatched checkpoint or
  an ordinary merge-triggered run must make zero tag, floating-tag, GitHub
  Release, OIDC, package, or deployment mutations; correlated response-loss
  readback is reported explicitly rather than blindly retried.
- [ ] Make standalone apply and `complete-protection` dry-run by default and
  require `--apply --confirm`. Let interactive staged provision capture the same
  typed confirmation after repository creation/scaffold, but do not report
  `full_applied` until the composite receipt is ready.
- [ ] Before each write re-read repository identity, slug/default branch,
  namespace, exact live ID, and before fingerprint. Follow each write with full
  semantic readback. Treat only the narrowly correlated rejected
  `tag_name_pattern` payload as a possible degraded variant, but never mutate to
  it under a confirmation that bound only the primary payload. The chosen
  implementation binds both exact payload fingerprints and the explicit
  `--allow-degraded-tag-pattern` choice into the original plan ID; without that
  flag, a 422 stops without a fallback write. It stays non-ready. Distinguish
  rejected writes from response-lost indeterminate state and never synthesize a
  cross-API rollback.
- [ ] After the last attempted operation, re-read repository identity/default
  branch and every classic, security, merge, full-ruleset, environment, and
  expected-check surface as one convergence barrier. Bind those final
  fingerprints to `ProtectionReceipt`; drift or unreadability on any earlier or
  just-written surface makes the receipt indeterminate/non-ready.
- [ ] On a ready provision/`complete-protection` apply, emit a canonical redacted
  receipt binding repository ID, ruleset IDs, plan ID, desired/live payload
  fingerprints, final convergence snapshot, and timestamp. When automatic
  retirement evidence is requested, sign it with an explicit operator SSH
  signing key whose public key/fingerprint and principal were preview-bound;
  publish the signed envelope to the Consumer tracking issue. Verification
  requires the signature against a current allowlisted GitHub SSH signing key,
  an author with current administrator permission, immutable comment/node/event
  IDs, and `lastEditedAt == null`. Reject forged, edited, deleted, revoked-key,
  or untrusted-author content. If signing or persistence fails, preserve local
  mutation truth but keep automatic future ruleset deletion blocked.
- [ ] Update infrastructure/security and onboarding/reconcile owners in this same
  commit with composite confirmation, explicit environment limits, receipt
  lifecycle, final convergence barrier, and degraded-plan consent.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" python scripts/regen-templates.py
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" python scripts/regen-templates.py --check
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_protection.py \
  tests/core/test_release_authorization.py tests/core/test_provision.py \
  tests/core/test_composition.py tests/core/test_compiler.py \
  tests/core/test_dayzero_profiles.py tests/core/test_onboarding.py \
  tests/test_cli_provision.py tests/test_cli_apply_rulesets.py \
  tests/test_github_platform.py tests/test_pipeline_privileges.py \
  tests/test_workflow_guards.py tests/test_cli_release.py \
  tests/test_validation_negative.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/core/protection.py aviato/core/release_authorization.py \
  aviato/core/model.py aviato/core/composition.py aviato/core/compiler.py \
  aviato/core/provision.py aviato/core/ports.py aviato/core/ruleset_plan.py \
  aviato/github.py aviato/github_platform.py aviato/cli.py \
  aviato/library/scaffold/wf-protection-checkpoint.yaml \
  aviato/library/scaffold/files/wf-protection-checkpoint.yml \
  aviato/library/pipelines.yaml aviato/library/workflow-envelopes.yaml \
  aviato/library/workflow-fragments/release-gate.yml \
  aviato/library/workflow-fragments/release-python.yml \
  aviato/library/workflow-fragments/release-node.yml \
  aviato/library/workflow-fragments/release-swift.yml \
  aviato/library/workflow-fragments/pypi-publish.yml \
  aviato/library/workflow-fragments/ghcr-publish.yml \
  aviato/library/workflow-fragments/app-store-connect.yml \
  aviato/library/workflow-fragments/docs-python-library.yml \
  aviato/library/workflow-fragments/docs-python-service.yml \
  aviato/library/workflow-fragments/docs-python-component.yml \
  aviato/library/workflow-fragments/docs-node-service.yml \
  aviato/library/workflow-fragments/docs-swift-app.yml \
  aviato/library/bundles/workflows/base.yaml \
  .github/workflows/reusable-release-gate.yml \
  .github/workflows/reusable-release.yml \
  .github/workflows/aviato-ci.yml \
  .github/workflows/aviato-protection-checkpoint.yml \
  templates/consumer-protection-checkpoint.yml \
  templates/profile-node-service.yml \
  templates/profile-python-component.yml \
  templates/profile-python-library.yml templates/profile-python-service.yml \
  templates/profile-swift-app.yml scripts/regen-templates.py aviato/validation.py \
  docs/architecture/infrastructure.md docs/architecture/security.md \
  docs/specifications/modules/onboarding/flow.md \
  docs/specifications/modules/reconcile/flow.md \
  tests/core/test_protection.py tests/core/test_release_authorization.py \
  tests/core/test_composition.py tests/core/test_compiler.py \
  tests/core/test_dayzero_profiles.py tests/core/test_onboarding.py \
  tests/core/test_provision.py tests/test_cli_provision.py \
  tests/test_cli_apply_rulesets.py tests/test_github_platform.py \
  tests/test_pipeline_privileges.py tests/test_workflow_guards.py \
  tests/test_cli_release.py tests/test_validation_negative.py
git commit -m "fix(protection): apply one complete confirmed plan"
```

### Task 12: Harden reconciliation and add protection capture/restore

**Files:**

- Modify: `aviato/core/protection.py`
- Modify: `aviato/core/reconcile.py`
- Modify: `aviato/core/reconcile_flow.py`
- Modify: `aviato/core/settings_drift_flow.py`
- Modify: `aviato/core/ports.py`
- Modify: `aviato/github_platform.py`
- Modify: `aviato/cli.py`
- Modify: `docs/requirements/core/state-and-failures.md`
- Modify: `docs/specifications/modules/reconcile/flow.md`
- Modify: `tests/core/test_protection.py`
- Modify: `tests/core/test_reconcile_flow.py`
- Modify: `tests/test_cli_reconcile.py`
- Modify: `tests/test_github_platform.py`
- Create: `tests/test_cli_protection_snapshot.py`

- [ ] Add failing tests named:

```text
test_reconcile_consent_binds_composite_plan_and_is_reread_before_first_write
test_reconcile_rechecks_each_surface_and_reports_completed_failed_and_unattempted
test_reconcile_response_loss_uses_readback_or_becomes_indeterminate
test_partial_receipt_is_recorded_even_when_audit_comment_fails
test_capture_protection_emits_redacted_semantic_schema_with_digest
test_protection_snapshot_round_trip_omits_unwriteable_get_metadata
test_restore_builds_purpose_specific_write_payloads_not_replayed_get_json
test_restore_defaults_to_preview_and_rejects_changed_confirmation_or_target
test_unknown_unsupported_or_malformed_captured_state_blocks_automatic_restore
test_restore_partial_result_requires_fresh_preview_for_recovery
```

Execute capture/restore through the CLI with fixture API state. Assert no secret
or raw authenticated body enters the snapshot and no read-shaped object is sent
back to the API.

- [ ] Bind reconciliation consent to the complete plan ID, re-read issue consent
  and the full plan immediately before the first write, then use the per-surface
  precondition/readback executor from Task 11. Always emit and attempt to persist
  a structured receipt; comment failure must not erase mutation truth.
- [ ] Add read-only `aviato capture-protection PATH --output FILE` producing a
  schema-1 `ProtectionSnapshot`: repository ID/node/slug/default branch, capture
  head/time, and canonical modeled classic, security, merge, environment, and
  full ruleset state with IDs/fingerprints plus unsupported descriptors.
- [ ] Add `aviato restore-protection PATH SNAPSHOT`, dry-run by default and
  `--apply --confirm` for mutation. Build purpose-specific payloads through the
  same `ProtectionPlan` executor. Refuse malformed/digest-mismatched snapshots,
  target/default-branch mismatch, and any unknown/unsupported captured field.
- [ ] Update the state/failure and reconcile specifications in this same commit
  with snapshot schema, purpose-built restoration, partial receipts, and
  unsupported-state escalation.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_protection.py tests/core/test_reconcile_flow.py \
  tests/test_cli_reconcile.py tests/test_cli_protection_snapshot.py \
  tests/test_github_platform.py tests/core/test_settings_drift_flow.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/core/protection.py aviato/core/reconcile.py aviato/core/reconcile_flow.py aviato/core/settings_drift_flow.py aviato/core/ports.py aviato/github_platform.py aviato/cli.py docs/requirements/core/state-and-failures.md docs/specifications/modules/reconcile/flow.md tests/core/test_protection.py tests/core/test_reconcile_flow.py tests/test_cli_reconcile.py tests/test_cli_protection_snapshot.py tests/test_github_platform.py
git commit -m "feat(reconcile): preserve semantic protection recovery"
```

### Task 13: Make doctor aggregate every applicable readiness signal

**Files:**

- Modify: `aviato/core/diagnosis.py`
- Modify: `aviato/core/inventory.py`
- Modify: `aviato/core/transition.py`
- Modify: `aviato/core/protection.py`
- Modify: `aviato/core/release_authorization.py`
- Modify: `aviato/github_platform.py`
- Modify: `aviato/cli.py`
- Modify: `docs/specifications/modules/fleet/diagnosis.md`
- Modify: `README.md`
- Modify: `docs/architecture/infrastructure.md`
- Modify: `docs/requirements/modules/fleet/backlog.md`
- Modify: `tests/core/test_diagnosis.py`
- Modify: `tests/core/test_release_authorization.py`
- Test: `tests/core/test_inventory.py`
- Test: `tests/core/test_transition.py`
- Test: `tests/core/test_protection.py`
- Test: `tests/test_github_platform.py`
- Modify: `tests/test_cli_doctor.py`
- Modify: `tests/test_cli_onboard.py`

- [ ] Add a parameterized failing matrix named:

```text
test_readiness_requires_every_artifact_clean
test_readiness_requires_inventory_marker_universe_and_zero_obsolete_conflicts
test_readiness_requires_no_journal_recovery_seed_secret_or_indeterminate_state
test_readiness_requires_local_and_remote_drift_automation_true
test_readiness_requires_every_local_and_remote_prerequisite_true
test_readiness_requires_issue_heartbeat_and_full_protection_true
test_readiness_requires_current_managed_checkpoint_workflow_and_admin_bypass_false
test_readiness_treats_false_and_unknown_as_non_ready_for_every_signal
test_readiness_all_green_vector_is_the_only_healthy_case
test_doctor_no_remote_probe_is_reporting_only_and_nonzero
test_doctor_uses_zero_unhealthy_one_and_two_malformed_or_usage
```

Flip each field to `False` and `None` independently and assert the exact named
blocker. The current exit decision must fail because it relies primarily on
drift automation.

- [ ] Expand `DiagnosisReport` with managed inventory/universe status, obsolete
  and conflict lists, recovery status, indeterminate remote mutations,
  full-protection state, and ordered `readiness_blockers`. Define
  `readiness_healthy` as true only for the all-positive vector in the approved
  design. Emit deterministic blocker IDs such as `artifact:<path>:missing`,
  `managed-inventory:corrupt`, `marker-universe:indeterminate`,
  `obsolete:<path>:retirable`, `recovery:pending`,
  `remote-prerequisite:<name>:unknown`, `authorization-guard:stale`,
  `environment:<name>:admin-bypass`, and `full-protection:unknown`. General
  onboarding readiness requires the generated managed checkpoint workflow and
  guard descriptor to match the pinned snapshot plus every privileged
  environment's live `can_admins_bypass == false`; it does not require a fresh
  tag-specific receipt until a release is attempted.
- [ ] Make `doctor` return `0` only when healthy, `1` for unhealthy or unproven
  applicable signals, and `2` for malformed configuration/operator usage.
  `--no-remote-probe` prints the unproven fields and stays `1`.
- [ ] Update the living diagnosis specification in the same commit so it names
  the aggregate contract and tri-state behavior.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_diagnosis.py \
  tests/core/test_release_authorization.py tests/core/test_inventory.py \
  tests/core/test_transition.py tests/core/test_protection.py \
  tests/test_github_platform.py tests/test_cli_doctor.py tests/test_cli_onboard.py
git diff --check
```

- [ ] Commit:

```bash
git add aviato/core/diagnosis.py aviato/core/inventory.py \
  aviato/core/transition.py aviato/core/protection.py \
  aviato/core/release_authorization.py aviato/github_platform.py aviato/cli.py \
  docs/specifications/modules/fleet/diagnosis.md README.md \
  docs/architecture/infrastructure.md \
  docs/requirements/modules/fleet/backlog.md tests/core/test_diagnosis.py \
  tests/core/test_release_authorization.py tests/test_cli_doctor.py \
  tests/test_cli_onboard.py
git commit -m "fix(doctor): fail closed on aggregate readiness"
```

## Wave 5: Harden managed and starter release boundaries

### Task 14: Freeze PyPI distributions before privileged publication

**Files:**

- Modify: `.github/workflows/reusable-pypi-publish.yml`
- Modify: `aviato/library/workflow-fragments/pypi-publish.yml`
- Generated/verify: `.github/workflows/aviato-ci.yml`
- Generated/verify: `templates/profile-python-library.yml`
- Modify: `docs/specifications/modules/deployment/pypi/requirements.md`
- Create: `tests/test_pypi_manifest.py`
- Modify: `tests/test_workflow_guards.py`
- Test: `tests/core/test_dayzero_profiles.py`
- Test: `tests/test_pipeline_privileges.py`
- Test: `tests/test_validation_negative.py`

- [ ] Extract and execute the real workflow Python bodies in failing tests named:

```text
test_distribution_manifest_is_deterministic_schema_versioned_and_outside_dist
test_distribution_manifest_accepts_only_regular_nonsymlink_wheel_and_sdist
test_distribution_manifest_rejects_empty_missing_mutated_duplicate_or_unlisted_set
test_distribution_manifest_rejects_traversal_directory_device_symlink_and_bad_suffix
test_distribution_manifest_rejects_bad_schema_key_digest_size_and_basename
test_publisher_validates_manifest_before_oidc_attestation_or_publish
test_pypi_manifest_binds_and_rechecks_managed_checkpoint_digest
test_pypi_confirmation_ignores_publisher_attestation_sidecars
test_pypi_confirmation_compares_exact_manifest_names_sizes_and_hashes
```

Serve local PEP 691 JSON for one wheel and one sdist and add the two matching
`*.publish.attestation` sidecars after the publish boundary. The current
confirmation must reproduce the historical false negative before the fix.

- [ ] Before editing either workflow, run this RED selection:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_pypi_manifest.py tests/test_workflow_guards.py \
  tests/core/test_dayzero_profiles.py tests/test_pipeline_privileges.py \
  tests/test_validation_negative.py
```

Expected: the executable sidecar regression and malformed-manifest cases fail
against the current confirmation script.

- [ ] In the unprivileged build job, after build/archive/metadata/audit checks and
  before upload, write schema-1 `aviato-pypi-manifest.json` outside `dist/` and
  the publisher `packages-dir`. Include sorted canonical basename, byte size,
  lowercase SHA-256 for a nonempty exact set of confined regular nonsymlink
  `.whl` and `.tar.gz` files, and the Task 11 managed checkpoint digest carried
  by the release gate.
- [ ] Upload the manifest with the immutable distribution/SBOM artifact. In the
  consumer-local publisher, validate schema, uniqueness, type, exact directory
  membership, size, and digest before any provenance, OIDC, attestation, or
  publish step. Revalidate the same fresh managed checkpoint and current
  `can_admins_bypass == false` immediately before OIDC. Reject every
  unmanifested distribution or authorization mismatch.
- [ ] After publication, reload the frozen manifest and confirm only its named
  distributions against PEP 691. Publisher-created sidecars never expand the
  expected set. Document the unprivileged-build-to-privileged-publisher identity
  contract without rewriting historical `0.3.0` evidence.
- [ ] Regenerate and verify:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" python scripts/regen-templates.py
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" python scripts/regen-templates.py --check
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_pypi_manifest.py tests/test_workflow_guards.py \
  tests/core/test_dayzero_profiles.py tests/test_pipeline_privileges.py \
  tests/test_validation_negative.py
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" python -m aviato.cli validate
git diff --check
```

- [ ] Commit:

```bash
git add .github/workflows/reusable-pypi-publish.yml .github/workflows/aviato-ci.yml aviato/library/workflow-fragments/pypi-publish.yml templates/profile-python-library.yml docs/specifications/modules/deployment/pypi/requirements.md tests/test_pypi_manifest.py tests/test_workflow_guards.py
git commit -m "fix(pypi): bind publication to frozen distributions"
```

### Task 15: Replace starter protection with a semantic dry-run installer

**Files:**

- Create: `starter/rulesets/ruleset-plan.py`
- Modify: `starter/rulesets/apply-rulesets.sh`
- Modify: `starter/rulesets/ruleset-branch.json`
- Delete: `starter/rulesets/ruleset-tag.json`
- Create: `starter/rulesets/ruleset-tag-creation.json`
- Create: `starter/rulesets/ruleset-tag-immutability.json`
- Create: `starter/rulesets/protection-checkpoint.py`
- Create: `starter/protection-checkpoint.yml`
- Modify: `starter/README.md`
- Create: `tests/test_starter_rulesets.py`
- Modify: `tests/test_workflow_guards.py`
- Modify: `tests/test_starter_governance.py`

- [ ] Execute the installer against a fake `gh` in failing tests named:

```text
test_starter_installer_preview_never_mutates_and_prints_semantic_plan
test_starter_installer_requires_exact_confirm_and_recomputes_before_apply
test_starter_installer_paginates_and_keys_rulesets_by_name_and_target
test_starter_installer_rejects_bad_slug_duplicates_changed_id_or_fingerprint
test_starter_branch_ruleset_has_no_bypass_strict_ci_and_codeql_high_critical
test_starter_branch_ruleset_dismisses_stale_reviews_and_resolves_threads
test_tag_creation_admin_authority_is_separate_from_no_bypass_immutability
test_codeql_default_setup_200_and_202_poll_to_configured
test_codeql_403_404_503_unknown_409_timeout_and_422_failure_block_readiness
test_starter_installer_reports_partial_indeterminate_and_unattempted_results
test_starter_installer_emits_redacted_repo_plan_payload_and_codeql_receipt
test_release_environment_requires_concrete_reviewer_and_no_self_review
test_release_environment_requires_can_admins_bypass_false_live_readback
test_release_authorization_requires_distinct_current_reviewer_signature
test_team_only_release_reviewer_cannot_authorize_without_trusted_membership_proof
test_receipt_binds_intended_tag_actor_and_authorizer_requires_actual_actor_match
test_release_environment_restricts_deployment_refs_to_authorized_release_tags
test_missing_stale_or_unreadable_release_environment_blocks_publication
test_installer_receipt_binds_tag_sha_environment_state_and_freshness
test_tag_pattern_lives_only_in_a_no_bypass_ruleset
test_local_protection_checkpoint_collects_then_distinct_reviewer_signs_receipt
test_local_protection_checkpoint_never_persists_or_prints_credential_or_raw_response
test_checkpoint_ceremony_never_shares_reviewer_private_key_or_operator_admin_token
test_checkpoint_intake_runs_only_trusted_default_branch_and_attests_signed_receipt
test_checkpoint_intake_has_no_environment_secret_app_or_administration_credential
test_tag_selected_workflow_cannot_access_checkpoint_readback_credential
test_checkpoint_intake_rejects_tag_ref_forged_stale_or_untrusted_signer_receipt
test_checkpoint_intake_binds_write_capable_submitter_separately_from_reviewer_signer
test_checkpoint_intake_treats_multiline_shell_expression_and_path_inputs_as_data
test_checkpoint_intake_permissions_are_exact_and_attestation_follows_verification
```

- [ ] Replace the standing branch admin bypass with the one-baseline posture:
  empty bypass actors, solo-maintainer zero-approval exception, stale-review
  dismissal, thread resolution, strict `ci`, CodeQL high/critical enforcement,
  deletion/non-fast-forward protection, and administrators subject to rules.
- [ ] Split tag creation from immutability. The release-tag creation ruleset uses
  the `creation` rule with only the administrator `RepositoryRole` in
  `bypass_mode: always` and contains no grammar rule. The no-bypass tag ruleset
  contains deletion, non-fast-forward, and the required `tag_name_pattern`, so
  the creation authority cannot bypass grammar or immutability. Report platform
  rejection as non-ready rather than equivalent protection.
- [ ] Make the installer validate `OWNER/REPO`, fetch paginated full details,
  match `(name,target)`, default to semantic preview, and require
  `--apply --confirm <plan-id>`. Re-read target/fingerprints before each write,
  read back afterward, and report structured partial outcomes.
- [ ] With the operator's local `gh` credential, configure CodeQL default setup
  before the branch ruleset, accepting `200` or bounded `202` polling only when
  readback reaches the required configured/language state. Emit a redacted
  receipt binding repository ID, plan ID, payload fingerprints, no-bypass
  readback, and CodeQL state for the later required-reviewer release checkpoint.
  Persist no credential.
- [ ] Extend the same semantic installer plan to configure and fully read back a
  protected `release` environment using explicit operator-supplied reviewer
  user/team IDs, self-review prevention, and a deployment-ref policy limited to
  authorized release tags. Require the live environment GET response's
  `can_admins_bypass` field to be exactly false. The installer never guesses an
  undocumented write: if true or missing, it emits a manual-UI prerequisite and
  remains non-ready until a separately approved operator action plus fresh
  readback proves false. The native no-bypass gate and the separate signed
  checkpoint receipt are both mandatory: its signer must be a currently
  configured concrete user reviewer, must differ from the tag actor, and every
  privileged job must validate the signature before any
  secret, OIDC request, or mutation. A missing reviewer, stale membership,
  missing independent signature, unsupported required API field, or unreadable
  environment is non-ready. For a release checkpoint, bind the
  receipt to exact intended tag/SHA, environment/ruleset/CodeQL fingerprints,
  reviewer identities, and capture time; require a fresh matching receipt before
  publication. Never auto-invent a reviewer.
- [ ] Add `starter/rulesets/protection-checkpoint.py` as the only component that
  performs the privileged pre-release readback. Its `collect` mode runs on the
  administrator/operator's local machine with the existing `gh` credential,
  accepts an intended tag/SHA, intended tag actor login, explicit concrete user
  release-environment reviewer, and separately identified write-capable workflow
  submitter, reads repository ID, full ruleset bypass state, CodeQL, and
  environment state including `can_admins_bypass == false`, and emits one
  canonical redacted unsigned receipt. Its
  credential-free `review-sign` mode lets that concrete reviewer inspect and SSH
  sign the exact receipt on a separate machine. Verify the signing key against
  the reviewer's current GitHub SSH-signing keys and require an exact configured
  user-reviewer match. A team-only reviewer configuration is non-ready unless a
  separate trusted current-membership proof mechanism is explicitly
  implemented; never trust a self-asserted membership claim. Require signer and
  intended tag actor to differ, and bind the signed receipt to repository ID,
  tag/SHA, intended tag actor, collector identity, installer plan ID, exact
  fingerprints, reviewer IDs, signer, submitter, and a short expiry. The tool may
  submit the non-secret
  receipt/signature to the intake workflow only under a separately approved
  external checkpoint; it never persists or prints the credential or raw API
  responses.
- [ ] Add the copyable no-secret intake workflow
  `starter/protection-checkpoint.yml` (consumer destination
  `.github/workflows/aviato-protection-checkpoint.yml`). It runs only by
  `workflow_dispatch` from the current trusted default branch, performs no
  checkout, has no environment or secret reference, has no GitHub App/PAT or
  Administration credential, and receives only the redacted signed receipt.
  Set workflow permissions to `{}` and pin every action by immutable SHA. A
  verifier job has only `contents: read`. Pass strictly length-bounded base64url
  receipt/signature inputs only through step environment variables into inline
  Python—never interpolate inputs into `run:`, shell, here-doc content,
  expression-built commands, paths, or action parameters. Decode into a fixed
  exclusive temporary file, reject
  duplicate/deep/oversized JSON, never `eval` or invoke a shell, and attest only
  the verifier-created fixed output after success. Its inline trusted verifier
  rejects malicious multiline, shell-expression, and path-like input as data,
  plus a tag-selected ref, an unexpected workflow
  identity/blob, a forged/untrusted/revoked signature, an edited payload, a
  stale receipt, a dispatch actor other than the separately receipt-bound
  submitter, or a repository/tag/SHA mismatch; the submitter need not equal the
  read-only reviewer/signer. It uploads one fixed-name verified-receipt artifact.
  A separate attestation job with exactly `contents: read`, `id-token: write`,
  and `attestations: write` receives only that successful fixed artifact—not raw
  dispatch inputs—and emits a GitHub OIDC artifact-attestation bundle for its
  digest. That bundle must be
  downloadable with `actions: read` and independently verifiable offline, so the
  later authorizer needs no Attestations, Administration, App, PAT, or secret
  permission. A tag-triggered
  workflow must be structurally unable to request any checkpoint readback
  credential because no such credential is stored in GitHub. Missing local
  readback, signature, trusted-default-branch intake, or attestation is
  non-ready.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_starter_rulesets.py tests/test_workflow_guards.py \
  tests/test_starter_governance.py
git diff --check
```

- [ ] Commit:

```bash
git add starter/rulesets/ruleset-plan.py starter/rulesets/apply-rulesets.sh \
  starter/rulesets/ruleset-branch.json starter/rulesets/ruleset-tag.json \
  starter/rulesets/ruleset-tag-creation.json \
  starter/rulesets/ruleset-tag-immutability.json \
  starter/rulesets/protection-checkpoint.py \
  starter/protection-checkpoint.yml starter/README.md \
  tests/test_starter_rulesets.py tests/test_workflow_guards.py \
  tests/test_starter_governance.py
git commit -m "fix(starter): require confirmed baseline protection"
```

### Task 16: Add the read-only starter release authorizer

**Files:**

- Create: `starter/release-authorizer.yml`
- Modify: `starter/python-library/release.yml`
- Modify: `starter/python-app/release.yml`
- Modify: `starter/node-service/release.yml`
- Modify: `starter/container-service/release.yml`
- Modify: `starter/docs-site/docs.yml`
- Modify: `starter/README.md`
- Create: `tests/test_starter_release_security.py`
- Modify: `tests/test_workflow_guards.py`

- [ ] Extract and execute the authorizer body with fake GitHub responses and real
  temporary Git refs in failing tests named:

```text
test_authorizer_has_only_contents_actions_and_checks_read_and_no_checkout
test_authorizer_resolves_and_bounded_peels_tag_to_one_commit
test_authorizer_requires_current_actor_admin_and_readable_permission
test_authorizer_requires_commit_reachable_from_current_default_branch
test_authorizer_requires_one_exact_successful_trusted_ci_result_for_sha
test_authorizer_rejects_stale_missing_skipped_duplicate_wrong_app_or_wrong_workflow_ci
test_authorizer_rejects_unreadable_api_repo_or_default_branch_change
test_authorizer_evidence_digest_binds_repo_tag_sha_actor_branch_workflow_and_check
test_build_manifest_carries_and_revalidates_authorizer_digest
test_privileged_jobs_never_checkout_or_execute_consumer_source_or_helpers
test_authorizer_rejects_wrong_event_ref_head_repo_attempt_or_workflow_blob
test_authorizer_requires_the_exact_required_job_and_check_set
test_authorizer_requires_actual_actor_equal_receipt_actor_and_not_signer
test_missing_deleted_stale_or_unattested_protection_receipt_blocks_authorizer
test_no_environment_or_receipt_blocks_every_privileged_starter_job
```

- [ ] Add the copyable local reusable workflow
  `starter/release-authorizer.yml` (consumer destination
  `.github/workflows/aviato-release-authorizer.yml`) and make every tag-based
  starter flow call it. Give the caller job only explicit `contents: read`,
  `actions: read`, and `checks: read` plus implicit metadata. It receives no
  secret, PAT, Attestations API permission, or administration token and performs
  no checkout.
- [ ] Resolve repository identity/default branch, validate SemVer, peel the event
  tag to one SHA, require the actor's current admin permission, fetch refs without
  checkout to prove protected-default-branch ancestry, and require one
  unambiguous successful trusted GitHub Actions CI workflow/check for that exact
  SHA. Bind and validate repository, immutable workflow ID/path/blob identity,
  approved event (`push` or explicitly modeled merge queue), head repository and
  ref, run attempt, and the exact required job/check set. Reject manual dispatch,
  pull-request forks, wrong refs/head repositories, relaxed/missing jobs,
  duplicate attempts/contexts, or any unreadable/ambiguous response.
- [ ] Emit canonical evidence JSON and SHA-256 over all authorization bindings as
  reusable-workflow outputs, including the full run/workflow/event/ref/attempt/
  job-set binding. Builders receive only the authorized SHA and evidence digest.
  Tests extract and execute the exact inline workflow script; privileged jobs
  may not checkout or execute consumer helper files.
- [ ] Find exactly one successful Task 15 no-secret checkpoint-intake run for the
  tag/SHA, then download and cryptographically verify its receipt and artifact
  attestation bundle offline against the exact trusted default-branch checkpoint
  workflow ID, path, blob/ref identity, `workflow_dispatch` event, run attempt,
  and issuer.
  Verify the concrete user-reviewer SSH signature and current GitHub SSH-signing
  key, require that exact user in the current environment reviewer set and
  distinct from the signed intended tag actor, require actual `github.actor` to
  equal that receipt-bound intended tag actor, and verify the intake run actor
  equals the separately receipt-bound submitter. Do not accept a self-asserted
  team membership claim. Repeat actual-actor equality and signer inequality in
  every privileged job before secret access, OIDC, or mutation.
  Require the receipt to be unexpired and bound to current repository ID, exact
  tag/SHA, CodeQL/ruleset/environment fingerprints, reviewer identities, and
  trust policy. With only `actions: read`, re-read the current `release`
  environment's existence, protection rules, and `can_admins_bypass`; deletion,
  automatic unprotected recreation, any value other than exactly false,
  stale/missing receipt, ambiguous intake runs, or any fingerprint mismatch
  blocks. Include the checkpoint receipt digest in authorizer outputs.
  No checkpoint, GitHub App, ruleset-write, Administration, or other readback
  credential exists in any GitHub environment or tag-selected workflow.
- [ ] In every starter privileged mutation job, before OIDC token use or the first
  contents/packages/pages write, independently verify the authorizer/checkpoint
  digest and current protected-environment readback again. Reference the
  `release` environment; when GitHub requires a different target environment
  such as `github-pages`, consume a dedicated no-write `release`-environment gate
  job and still reverify its receipt. Never treat an environment reference alone
  as proof because a missing environment can be auto-created without protection.
  Structural and end-to-end fake-API tests begin with no environment/receipt and
  require every mutation path to stop.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_starter_release_security.py \
  tests/test_workflow_guards.py tests/test_starter_governance.py
git diff --check
```

- [ ] Commit:

```bash
git add starter/release-authorizer.yml starter/python-library/release.yml starter/python-app/release.yml starter/node-service/release.yml starter/container-service/release.yml starter/docs-site/docs.yml starter/README.md tests/test_starter_release_security.py tests/test_workflow_guards.py
git commit -m "feat(starter): authorize release tags without secrets"
```

### Task 17: Isolate starter PyPI and GitHub Release promotion

**Files:**

- Modify: `starter/python-library/release.yml`
- Modify: `starter/python-app/release.yml`
- Modify: `starter/node-service/release.yml`
- Modify: `starter/README.md`
- Modify: `tests/test_starter_release_security.py`
- Modify: `tests/test_pypi_manifest.py`
- Modify: `tests/test_workflow_guards.py`

- [ ] Add failing executable/structural tests named:

```text
test_starter_python_build_is_read_only_and_freezes_exact_distributions
test_starter_pypi_publisher_has_only_oidc_scope_no_checkout_or_build
test_starter_pypi_manifest_attestation_remote_and_clean_install_are_one_identity
test_starter_github_release_uploads_only_prebuilt_manifested_assets
test_starter_release_rechecks_tag_target_and_asset_hashes_before_write
test_starter_release_readback_uses_api_digest_or_download_rehash
test_starter_privileged_jobs_forbid_install_build_eval_and_consumer_commands
test_starter_publish_jobs_share_no_unnecessary_write_permission
```

- [ ] Split Python Library into authorize, read-only checkout/build/twine/manifest,
  isolated OIDC publish, and separate contents-write GitHub Release jobs. Thread
  the authorizer digest through the immutable distribution manifest and verify it
  inline immediately before each mutation together with the attested protection
  checkpoint and fresh current-environment protection readback. Confirm PEP 691
  and clean exact-version installation from the published index.
- [ ] Split Python App and Node Service release paths into an unprivileged
  build/manifest stage where assets exist and a no-checkout contents-write
  release stage. If there are no assets, still bind release creation to the
  authorizer/tag SHA and verify the API target after creation.
- [ ] Upload manifested assets once, then compare API-reported digests or download
  and rehash if the API omits them. No privileged job may rebuild, install, or
  execute consumer source.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_starter_release_security.py \
  tests/test_pypi_manifest.py tests/test_workflow_guards.py
git diff --check
```

- [ ] Commit:

```bash
git add starter/python-library/release.yml starter/python-app/release.yml starter/node-service/release.yml starter/README.md tests/test_starter_release_security.py tests/test_pypi_manifest.py tests/test_workflow_guards.py
git commit -m "fix(starter): promote verified release artifacts"
```

### Task 18: Preserve byte identity through starter GHCR and Pages promotion

**Files:**

- Modify: `starter/container-service/release.yml`
- Modify: `starter/docs-site/docs.yml`
- Modify: `starter/README.md`
- Modify: `tests/test_starter_release_security.py`
- Modify: `tests/test_workflow_guards.py`

- [ ] Add failing tests named:

```text
test_starter_ghcr_builder_emits_canonical_oci_archive_digest_and_scan_binding
test_starter_ghcr_publisher_pushes_without_rebuild_and_verifies_remote_arch_digests
test_starter_ghcr_index_and_alias_resolve_to_manifested_immutable_digests
test_starter_pages_builder_binds_source_branch_commit_tree_bundle_and_site_hash
test_starter_pages_push_verifies_and_fast_forwards_the_exact_bundle_without_checkout
test_starter_pages_deploy_consumes_the_same_prebuilt_site_artifact_without_rebuild
test_starter_pages_readback_binds_branch_run_artifact_and_served_tree
test_starter_every_target_forbids_rebuild_after_privilege_gate
test_starter_ghcr_older_interleaved_release_cannot_move_latest_backward
test_starter_ghcr_alias_response_loss_requires_full_remote_readback
```

Use executable manifest helpers with fixture OCI layouts/site trees and structural
workflow parsing. A manifest sitting beside an artifact is insufficient: tests
must prove scanner input, publisher input, and remote output identity.

- [ ] Make native architecture builders read-only with respect to packages. Emit
  canonical OCI archives/layouts plus digests; bind Trivy's exact input digest
  and scan-result hash. In isolated no-checkout package-write jobs, rehash and
  push without rebuilding, resolve remote per-architecture digests, construct the
  index only from those digests, and verify version/monotonic aliases. Serialize
  repository release promotion across runs, then immediately before each
  floating-alias write re-read its current digest/version and refuse a backward
  move. Perform a final remote index/alias reread; response loss remains
  indeterminate unless that readback proves the intended monotonic state.
- [ ] Make GHCR, Pages push/deploy, and GitHub Release mutation jobs reverify the
  attested protection checkpoint plus current protected `release` environment
  immediately before their first write; an absent/auto-created/stale environment
  stops the target even if upstream build/scan jobs passed.
- [ ] For Pages, make the read-only builder record source SHA, docs-branch commit
  and tree, bundle hash, archived site-tree hash, and Pages artifact identity.
  Replace the privileged push job's checkout with an empty temporary Git
  repository that fetches only the current `gh-pages` ref when present, verifies
  and fast-forwards the downloaded exact bundle, and pushes its authorized ref.
  Deployment consumes the same prebuilt site artifact. Read back
  branch/run/site evidence without rebuilding.
- [ ] Keep GitHub Release creation in a separate least-privilege job and carry the
  authorizer evidence digest through both target manifests.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_starter_release_security.py tests/test_workflow_guards.py
git diff --check
```

- [ ] Commit:

```bash
git add starter/container-service/release.yml starter/docs-site/docs.yml starter/README.md tests/test_starter_release_security.py tests/test_workflow_guards.py
git commit -m "fix(starter): preserve deployment byte identity"
```

## Wave 6: Correct validation, packaging, and living ownership

### Task 19: Surface non-gating zizmor warnings without weakening failures

**Files:**

- Modify: `aviato/plugins/zizmor_scan.py`
- Modify: `aviato/plugins/actionpins.py`
- Modify: `aviato/validation.py`
- Modify: `aviato/cli.py`
- Modify: `scripts/validate.sh`
- Modify: `.github/workflows/reusable-common-lint.yml`
- Modify: `docs/specifications/modules/security/supply-chain.md`
- Modify: `tests/core/test_zizmor_scan.py`
- Modify: `tests/core/test_actionpins.py`
- Modify: `tests/test_cli_lint_actions.py`
- Modify: `tests/test_validation.py`
- Modify: `tests/test_workflow_guards.py`

- [ ] Add failing tests named:

```text
test_unknown_well_formed_zizmor_audit_is_warning
test_mixed_gated_and_warning_audits_are_sorted_and_deduplicated
test_malformed_zizmor_item_or_top_level_shape_fails_closed
test_zizmor_item_requires_string_ident_and_structural_locations
test_lint_actions_warning_only_is_visible_and_zero
test_lint_actions_gated_finding_is_visible_and_nonzero
test_validate_and_strict_ci_print_warnings_without_gating
test_common_lint_uses_the_single_warning_capable_implementation
```

- [ ] Add frozen `ZizmorScanResult(violations, warnings)` and compatible
  `SupplyChainScan` composition. Validate every JSON item and location. Map gated
  audit IDs to violations and all other well-formed audit IDs—including the
  frozen non-gating `dangerous-triggers` decision—to warnings. Treat malformed
  JSON/items/top-level shape and tool failure as violations.
- [ ] Thread warnings through `lint-actions`, `aviato validate`, the strict script,
  and reusable CI logs while keeping warnings-only exit zero and all gated or
  corrupted output nonzero.
- [ ] Correct the supply-chain specification to the accepted bashlex block-level,
  order/artifact-insensitive verifier. Preserve the already approved
  `dangerous-triggers` and mutable-shell `docker run` exclusions; do not silently
  reopen them.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/core/test_zizmor_scan.py tests/core/test_actionpins.py \
  tests/test_cli_lint_actions.py tests/test_validation.py tests/test_workflow_guards.py \
  tests/test_local_gate.py
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" python -m aviato.cli validate
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh
git diff --check
```

- [ ] Commit:

```bash
git add aviato/plugins/zizmor_scan.py aviato/plugins/actionpins.py aviato/validation.py aviato/cli.py scripts/validate.sh .github/workflows/reusable-common-lint.yml docs/specifications/modules/security/supply-chain.md tests/core/test_zizmor_scan.py tests/core/test_actionpins.py tests/test_cli_lint_actions.py tests/test_validation.py tests/test_workflow_guards.py
git commit -m "fix(security): report non-gating zizmor warnings"
```

### Task 20: Exclude sibling worktrees from the real YAML gate

**Files:**

- Modify: `.yamllint.yml`
- Modify: `tests/test_local_gate.py`
- Modify: `docs/architecture/validation.md`

- [ ] Add an executable failing test named
  `test_yamllint_relative_gate_ignores_sibling_worktree`. Copy the real config to
  a temporary repository, add valid root YAML and deliberately invalid
  `.worktrees/sibling/generated.yml`, then run exactly `yamllint -s .` with that
  temporary root as `cwd`. The current config must report the nested invalid file.
- [ ] Add `.worktrees/**` to the yamllint ignore set. Retain the existing semantic
  assertion that `scripts/validate.sh` invokes the same relative command; do not
  replace the executable test with a token check.
- [ ] Run focused and topology verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_local_gate.py
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" yamllint -s .
git diff --check
```

Expected: the executable focused test creates and removes its synthetic invalid
sibling-worktree fixture, and the exact relative gate passes in the real
worktree.

- [ ] Commit:

```bash
git add .yamllint.yml tests/test_local_gate.py docs/architecture/validation.md
git commit -m "fix(validation): ignore linked worktrees in yamllint"
```

### Task 21: Publish README long-description metadata in both distributions

**Files:**

- Modify: `pyproject.toml`
- Modify: `scripts/validate.sh`
- Modify: `tests/test_cli_release.py`
- Modify: `docs/architecture/validation.md`
- Modify: `docs/requirements/modules/versioning/backlog.md`

- [ ] Add a failing integration test named
  `test_built_wheel_and_sdist_include_markdown_readme_metadata`. Build both formats
  with `python -m build --no-isolation --outdir <tmp>`, parse the wheel's sole
  `.dist-info/METADATA` and sdist's top-level `PKG-INFO`, and require matching
  versions, `Description-Content-Type: text/markdown`, and normalized description
  bodies byte-equivalent to the complete normalized `README.md` and to each
  other. A heading-only or truncated description must fail.
- [ ] Add
  `readme = {file = "README.md", content-type = "text/markdown"}` under
  `[project]`. Change the strict local gate from wheel-only to wheel+sdist build,
  inspect both metadata documents, then perform its isolated wheel install.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_cli_release.py tests/test_local_gate.py
tmp_root="${TMPDIR:-/tmp}"
dist_dir="$(mktemp -d "${tmp_root%/}/aviato-readiness-dist.XXXXXX")"
trap 'rm -rf -- "$dist_dir"' EXIT
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
python -m build --no-isolation --outdir "$dist_dir"
git diff --check
```

- [ ] Commit:

```bash
git add pyproject.toml scripts/validate.sh tests/test_cli_release.py docs/architecture/validation.md docs/requirements/modules/versioning/backlog.md
git commit -m "fix(package): publish README metadata"
```

### Task 22: Reconcile living state and add canonical OR traceability

**Files:**

- Create: `docs/evidence/rollout/2026-07-14-aviato.yml`
- Modify: `README.md`
- Modify: `docs/architecture/{overview,data-flow,infrastructure,security,validation}.md`
- Modify: `docs/requirements/traceability.md`
- Modify: `docs/requirements/core/{definition-of-done,modularity,structure,state-and-failures}.md`
- Modify: `docs/requirements/core/backlog.md`
- Modify: `docs/requirements/modules/README.md`
- Modify: `docs/requirements/modules/deployment/README.md`
- Modify: `docs/requirements/modules/onboarding/backlog.md`
- Modify: `docs/requirements/modules/scaffolding/backlog.md`
- Modify: `docs/requirements/modules/fleet/backlog.md`
- Modify: `docs/requirements/modules/reconcile/backlog.md`
- Modify: `docs/requirements/modules/security/backlog.md`
- Modify: `docs/requirements/modules/starter-kit/conventions.md`
- Modify: `docs/requirements/modules/starter-kit/backlog.md`
- Modify: `docs/requirements/modules/deployment/backlog.md`
- Modify: `docs/requirements/modules/deployment/{pypi,ghcr,docs-site,apple}/backlog.md`
- Modify: `docs/security/controls.md`
- Modify: `docs/security/threat-model.md`
- Modify: `docs/specifications/core/consumer-contract.md`
- Modify: `docs/specifications/modules/onboarding/{flow,bootstrap}.md`
- Modify: `docs/specifications/modules/scaffolding/sync.md`
- Modify: `docs/specifications/modules/fleet/{diagnosis,scan}.md`
- Modify: `docs/specifications/modules/drift/{file-drift,settings-drift}.md`
- Modify: `docs/specifications/modules/versioning/{release,repin}.md`
- Modify: `docs/specifications/modules/offboarding/flow.md`
- Modify: `docs/specifications/modules/reconcile/{consent,flow}.md`
- Modify: `docs/specifications/modules/security/{scanning,supply-chain}.md`
- Modify: `docs/specifications/modules/deployment/{pypi,ghcr,docs-site,apple}/requirements.md`
- Modify: `docs/specifications/modules/starter-kit/documentation-governance.md`
- Modify: `starter/README.md`
- Modify: `docs/superpowers/plans/2026-07-12-repository-integrity-release-hardening.md`
- Modify: `tests/test_docs_index.py`
- Modify: `tests/test_starter_governance.py`
- Create: `tests/test_readiness_traceability.py`

- [ ] Add semantic failing tests that parse structured state and require:

```text
exactly one OR-001 through OR-022 traceability row
implemented or verified OR rows link implementation/tests while blocked rows link exact owner/backlog/blocker
no failed or unknown proof is marked verified
every disabled control or unproven target retains an owning backlog
rollout prose and backlogs agree with the freshly captured PR/release/control snapshot
the historical 0.3.0 confirmation failure remains failed after successful upload
OR-022 remains blocked without a validator-successful five-profile manifest
```

- [ ] Re-read the live state without mutation, then store a redacted semantic
  snapshot. At minimum query and reconcile PRs 42, 59, 60, 62, and 63 with exact
  current states/SHAs; tags `0.3.0` and `0`; Release `0.3.0`; the historical
  run/job and publish/confirmation step conclusions; and current
  automated-security-fix enabled/paused state. Tests validate snapshot schema and
  cross-document consistency against its captured values, never hard-code a
  mutable PR status. If any value differs from the planning snapshot, record the
  new fact rather than forcing the old expectation.
- [ ] Add OR-001 through OR-022 to the canonical traceability matrix. Every
  implemented/verified row links its durable implementation and tests; a still
  blocked row links its canonical owner, exact blocker, and owning backlog
  without inventing missing evidence. OR-001 through OR-019 and OR-021 become
  verified only after linked behavioral evidence passes. Tasks 23 and 24 add the
  OR-020 and OR-022 implementation/evidence links. OR-022 remains blocked until a
  real external release manifest passes Task 24's authenticated live verifier.
- [ ] Promote durable behavior into the named requirements, starter/security
  owners, architecture/data-flow records, consumer/onboarding/sync/repin/
  offboarding/reconcile/diagnosis/security/deployment specifications, and
  affected backlogs. Correct the stale dated hardening plan. Replace
  token-presence assertions with semantic YAML/matrix consistency tests.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_docs_index.py tests/test_starter_governance.py \
  tests/test_readiness_traceability.py
git diff --check
```

- [ ] Commit:

```bash
git add README.md docs/evidence/rollout/2026-07-14-aviato.yml \
  docs/architecture/overview.md docs/architecture/data-flow.md \
  docs/architecture/infrastructure.md docs/architecture/security.md \
  docs/architecture/validation.md docs/requirements/traceability.md \
  docs/requirements/core/definition-of-done.md \
  docs/requirements/core/modularity.md docs/requirements/core/structure.md \
  docs/requirements/core/state-and-failures.md \
  docs/requirements/core/backlog.md docs/requirements/modules/README.md \
  docs/requirements/modules/deployment/README.md \
  docs/requirements/modules/onboarding/backlog.md \
  docs/requirements/modules/scaffolding/backlog.md \
  docs/requirements/modules/fleet/backlog.md \
  docs/requirements/modules/reconcile/backlog.md \
  docs/requirements/modules/security/backlog.md \
  docs/requirements/modules/starter-kit/conventions.md \
  docs/requirements/modules/starter-kit/backlog.md \
  docs/requirements/modules/deployment/backlog.md \
  docs/requirements/modules/deployment/pypi/backlog.md \
  docs/requirements/modules/deployment/ghcr/backlog.md \
  docs/requirements/modules/deployment/docs-site/backlog.md \
  docs/requirements/modules/deployment/apple/backlog.md \
  docs/security/controls.md docs/security/threat-model.md \
  docs/specifications/core/consumer-contract.md \
  docs/specifications/modules/onboarding/flow.md \
  docs/specifications/modules/onboarding/bootstrap.md \
  docs/specifications/modules/scaffolding/sync.md \
  docs/specifications/modules/fleet/diagnosis.md \
  docs/specifications/modules/fleet/scan.md \
  docs/specifications/modules/drift/file-drift.md \
  docs/specifications/modules/drift/settings-drift.md \
  docs/specifications/modules/versioning/release.md \
  docs/specifications/modules/versioning/repin.md \
  docs/specifications/modules/offboarding/flow.md \
  docs/specifications/modules/reconcile/consent.md \
  docs/specifications/modules/reconcile/flow.md \
  docs/specifications/modules/security/scanning.md \
  docs/specifications/modules/security/supply-chain.md \
  docs/specifications/modules/deployment/pypi/requirements.md \
  docs/specifications/modules/deployment/ghcr/requirements.md \
  docs/specifications/modules/deployment/docs-site/requirements.md \
  docs/specifications/modules/deployment/apple/requirements.md \
  docs/specifications/modules/starter-kit/documentation-governance.md \
  starter/README.md \
  docs/superpowers/plans/2026-07-12-repository-integrity-release-hardening.md \
  tests/test_docs_index.py tests/test_starter_governance.py \
  tests/test_readiness_traceability.py
git commit -m "docs(readiness): reconcile findings and live state"
```

### Task 23: Add the onboarding pilot and recovery runbook

**Files:**

- Create: `docs/runbooks/onboarding-pilot-and-recovery.md`
- Modify: `README.md`
- Modify: `docs/architecture/data-flow.md`
- Modify: `docs/requirements/modules/onboarding/backlog.md`
- Modify: `docs/requirements/traceability.md`
- Create: `tests/test_onboarding_runbook.py`

- [ ] Add a failing parser test requiring these ordered runbook sections:

```text
authority and disposable-pilot boundary
pre-mutation repository and protection snapshot
pinned transition preview
temporary-clone execution and diagnosis
proposal and exact-SHA CI/security proof
protection preview, confirmation, readback, and doctor
abort criteria
transition journal inspection, resume, and rollback
purpose-built protection restoration
evidence preservation and separately authorized cleanup
```

Require evidence fields for slug/repository ID/default branch/head/dirty state,
declaration, seed sidecar, inventory, affected files, classic/security/merge
settings, environments/checks, and full rulesets. Extract shell blocks and
require the actual commands:

```bash
aviato recover-transition PATH
aviato recover-transition PATH --resume --confirm JOURNAL_ID
aviato recover-transition PATH --rollback --confirm JOURNAL_ID
aviato capture-protection PATH --output FILE
aviato restore-protection PATH FILE
aviato restore-protection PATH FILE --apply --confirm PLAN_ID
```

- [ ] Write the staged pilot. Abort on changed plan/ref, untrusted path,
  unexpected normalization, failed exact-SHA CI, unknown remote state, or any
  unreported partial mutation. Explicitly prohibit replaying raw GET-shaped API
  responses; restoration builds purpose-specific payloads, previews/confirms,
  binds target/default branch, reads back every surface, and escalates unknown
  captured fields to manual recovery.
- [ ] Link the runbook from operator entry points and OR-020 traceability. Keep
  mutation and cleanup authority checkpoints explicit.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_onboarding_runbook.py tests/test_docs_index.py \
  tests/test_readiness_traceability.py
git diff --check
```

- [ ] Commit:

```bash
git add docs/runbooks/onboarding-pilot-and-recovery.md README.md docs/architecture/data-flow.md docs/requirements/modules/onboarding/backlog.md docs/requirements/traceability.md tests/test_onboarding_runbook.py
git commit -m "docs(onboarding): add pilot and recovery runbook"
```

### Task 24: Add fail-closed release-scoped evidence validation

**Files:**

- Create: `docs/evidence/onboarding-readiness/README.md`
- Create: `docs/evidence/onboarding-readiness/schema-v1.yml`
- Create: `docs/evidence/onboarding-readiness/trust-policy-v1.yml`
- Create: `.github/workflows/verify-onboarding-evidence.yml`
- Create: `scripts/verify-onboarding-evidence.py`
- Create: `tests/test_onboarding_evidence.py`
- Modify: `docs/requirements/traceability.md`
- Modify: `docs/requirements/core/backlog.md`
- Modify: `docs/requirements/modules/deployment/backlog.md`
- Modify: `docs/requirements/modules/deployment/{pypi,ghcr,docs-site,apple}/backlog.md`

- [ ] Begin with failing tests named:

```text
test_schema_only_never_closes_and_live_snapshot_requires_authenticated_success
test_verify_live_emits_unsigned_sanitized_snapshot_then_reviewer_signs_it
test_verify_snapshot_reproduces_all_comparisons_without_credentials
test_evidence_workflow_has_no_environment_secret_app_or_app_store_credential
test_tag_or_alternate_workflow_cannot_access_evidence_readback_credentials
test_evidence_dispatch_inputs_are_bounded_data_never_shell_or_path_injection
test_evidence_release_id_derives_one_exact_manifest_and_sidecar_path_set
test_evidence_signer_key_trust_commit_path_and_workflow_identity_are_bound
test_signed_live_receipt_exit_and_snapshot_digest_are_bound_into_final_receipt
test_attestation_job_receives_only_successful_fixed_comparator_artifact
test_missing_bad_scope_stale_tampered_forged_or_untrusted_snapshot_fails_closed
test_complete_five_profile_matrix_and_ordered_recovery_pilot_are_required
```

- [ ] Add temporary complete and incomplete fixtures outside `docs/evidence` and
  invoke the real validator in explicit `--schema-only` and `--verify-live`
  modes. Schema-only success means structurally complete but never verified.
  Add `--verify-snapshot` for deterministic comparison of a signed sanitized
  authoritative snapshot without any credential. Require live-collection exit
  `0` only from authenticated live verification of a
  complete matrix, `1` for structurally valid but unverified/failed/blocked/
  unknown/incomplete evidence, and `2` for malformed schema or usage.
- [ ] For a strict release identifier `<release>`, define exactly one durable
  input set under `docs/evidence/onboarding-readiness/releases/`:
  `<release>.yml`, `<release>.snapshot.json`,
  `<release>.live-receipt.json`, `<release>.review-envelope.json`, and
  `<release>.review-envelope.sig`. The signed envelope binds the other three
  content digests plus verifier/trust-policy identity. Reject alternate suffixes,
  missing/extra sidecars, symlinks, aliases, or caller-supplied paths; fixtures
  live outside the durable evidence directory.
- [ ] Require exactly `python-library`, `python-service`, `node-service`,
  `python-component`, and `swift-app`. Every row binds release/pin/SHA,
  repository ID/slug/head, declaration and resolved snapshot, transition and
  protection plan/receipt IDs, doctor output/exit, exact-SHA checks, workflow/job
  URLs/conclusions, target identities/digests, rollback result, and cleanup
  state. Every protection receipt includes per-surface action/status plus before,
  after, and final-convergence fingerprints for settings, full rulesets,
  environments, and checks.
- [ ] Require exactly one matrix row to be the disposable pilot and validate an
  ordered timestamp/evidence chain that precedes every other target: snapshot,
  transition preview, journal inspection/interruption, resume or rollback,
  proposal/exact-SHA CI, protection apply/readback, semantic protection restore,
  re-onboarding convergence, and final doctor. Reject a matrix that has profile
  rows but no complete recovery pilot.
- [ ] Validate target-specific contracts: TestPyPI files/manifest/attestations/
  install and Pages identity for Python Library; multi-architecture GHCR scan,
  SBOM/provenance/index/alias identity for Python and Node services;
  zero-deployment proof for Python Component; and protected-environment/App Store
  delivery/build/TestFlight receipt for Swift App.
- [ ] Prove rejection of missing/duplicate/unknown profiles, wrong pin/SHA,
  unsuccessful required jobs, unbound hashes, absent rollback, missing or blocked
  Apple, unknown cleanup, malformed URL/digest/ID fields, missing per-surface
  readback, unordered pilot checkpoints, plausible-but-nonexistent URLs,
  wrong-run artifacts, wrong trusted workflow identity, tampered receipts,
  malicious manifest URLs, cross-origin redirects, proxy/private-IP targets,
  missing credential scopes, or any attempted mutation method. A synthetic
  complete fixture is test data only and never durable proof.
- [ ] Implement trust-policy-backed verification. Verify GitHub/Sigstore artifact
  attestations and target receipts against repository ID, workflow path/blob,
  event/ref, run/job/attempt, subject digest, and expected issuer. In
  `--verify-live`, use current operator credentials only in memory to re-read
  GitHub repository/ruleset/environment/run/artifact state, TestPyPI/PyPI PEP 691
  plus attestations, GHCR OCI manifests/provenance/SBOM, Pages branch/artifact/
  served-tree identity, and App Store Connect/TestFlight delivery state. Derive
  every network endpoint from schema-validated IDs plus a fixed HTTPS host/path
  allowlist in the trust policy—never from manifest display URLs. Disable proxy
  inheritance and cross-origin redirects, reject private/link-local/loopback DNS
  resolutions, bound response size/time, and prevent credentials from being sent
  outside their exact origin. Compare every authoritative value to the manifest
  and fail closed on auth gaps, disappearance, ambiguity, or normalization drift.
- [ ] Emit a canonical verification receipt binding validator version, trust
  policy digest, manifest digest, authoritative response/attestation digests,
  per-adapter conclusions, verification time, collector release/SHA, and a
  canonical sanitized authoritative snapshot. `--verify-live` runs only on the
  collector/operator's local machine, emits unsigned snapshot/receipt data, and
  never prints or persists credentials/raw responses. A credential-free
  `--review-sign` mode lets a distinct trust-policy-authorized evidence reviewer
  inspect and SSH sign one canonical envelope containing both the live receipt
  digest and sanitized snapshot digest; it verifies the reviewer's key against
  current GitHub SSH-signing keys and binds collector, reviewer, collector exit
  and adapter conclusions, manifest, snapshot, trust policy, verifier
  release/SHA, and expiry. The later
  no-secret evidence workflow verifies and attests the final receipt.
  Offline schema validity or a merely local signed receipt can never close
  traceability.
- [ ] Add a no-secret evidence-verification workflow on trusted default-branch
  code with three privilege-separated jobs. Set workflow permissions to `{}` and
  pin every action by immutable SHA. A `contents: read` input job accepts only an
  immutable evidence commit plus the strict release identifier, derives the five
  exact paths above itself, and fetches them through fixed GitHub API endpoints
  without checkout, and uses safe resource-bounded YAML/JSON parsing. Pass
  strictly length/charset-bounded dispatch values only through step environment
  variables into inline Python—never interpolate them into `run:`, shell,
  here-doc content, commands, paths, or action parameters. Resolve paths inside
  the allowed evidence root, reject symlinks/duplicates/deep or oversized input,
  verify the authorized reviewer SSH signature and current key, require the
  signed envelope to bind both exact input digests, collector exit `0`, every
  adapter conclusion, and verifier/trust-policy identity, and emit a fixed-name
  canonical artifact containing those bindings, IDs, and sanitized state only.
  Require the run event to be `workflow_dispatch` and bind current repository ID,
  default branch, workflow ID/path/blob/ref, run/attempt, dispatch actor,
  evidence commit, trust-policy digest, and signer; reject a tag-selected or
  non-default-branch workflow identity before parsing evidence data.
  A second `contents: read` comparator job fetches the exact trust-policy-bound
  validator blob from the current default branch through a fixed Contents API
  path, verifies its blob/digest, and runs it in `--verify-snapshot` mode against
  that fixed artifact and manifest. It never imports or executes the evidence
  commit. It reproduces every comparison and emits a fixed-name canonical
  receipt binding the verified live-receipt and snapshot digests, collector
  exit/conclusions, comparator exit/conclusions, and signer. A final
  job with exactly `contents: read`, `id-token: write`, and
  `attestations: write` receives only the successful comparator artifact—not raw
  dispatch/evidence strings—and creates the OIDC artifact-attestation bundle for
  its digest. It has no environment, secret, GitHub App, PAT, App Store key, or
  other live-read credential. Unsupported repository-plan attestation capability
  is an explicit non-ready blocker, never a silent unsigned fallback.
- [ ] Document the operator-local GitHub/App Store credential scope, in-memory
  handling, rotation/revocation, authorized evidence signer policy, snapshot
  redaction, short expiry, and separate external approval needed to perform live
  collection or submit evidence. Tests require missing/insufficient local scopes
  to fail closed; forbid mutation methods; prove tag/alternate workflows cannot
  access a credential because none is stored in GitHub; inject multiline shell
  expressions, traversal, duplicate keys, symlinks, redirects, and oversized
  payloads as inert data; reject any workflow that checks out or executes
  evidence-branch code; and prove the attestation job cannot run before a
  successful signed-snapshot comparison.
- [ ] Make traceability dynamic: without a real manifest under
  `docs/evidence/onboarding-readiness/releases/<release>.yml` plus a trusted
  attested receipt whose bound operator-local `--verify-live` collection returned
  zero and whose `--verify-snapshot` comparison returned zero, OR-022 and all
  dependent leaf/aggregate rows remain blocked/open.
- [ ] Run focused verification:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_onboarding_evidence.py \
  tests/test_readiness_traceability.py tests/test_docs_index.py
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
python scripts/verify-onboarding-evidence.py --help
git diff --check
```

- [ ] Commit:

```bash
git add docs/evidence/onboarding-readiness/README.md \
  docs/evidence/onboarding-readiness/schema-v1.yml \
  docs/evidence/onboarding-readiness/trust-policy-v1.yml \
  .github/workflows/verify-onboarding-evidence.yml \
  scripts/verify-onboarding-evidence.py tests/test_onboarding_evidence.py \
  docs/requirements/traceability.md docs/requirements/core/backlog.md \
  docs/requirements/modules/deployment/backlog.md \
  docs/requirements/modules/deployment/pypi/backlog.md \
  docs/requirements/modules/deployment/ghcr/backlog.md \
  docs/requirements/modules/deployment/docs-site/backlog.md \
  docs/requirements/modules/deployment/apple/backlog.md
git commit -m "feat(evidence): validate onboarding readiness matrix"
```

## Wave 7: Verify the complete local remediation

### Task 25: Run repository-wide gates and independent OR review

**Files:**

- Verify: all files changed by Tasks 2–24
- Verify: `docs/superpowers/specs/2026-07-14-onboarding-readiness-remediation-design.md`
- Verify: `docs/requirements/traceability.md`
- Update locally if ignored: `.superpowers/sdd/progress.md`

- [ ] Read and use `superpowers:requesting-code-review` and
  `superpowers:verification-before-completion`. Dispatch independent reviewers
  for: pinned context/compiler/transitions; rulesets/protection/diagnosis;
  managed/starter release security; and docs/evidence/operations. Require an
  OR-001–OR-022 requirement-to-implementation-to-test matrix, not a generic diff
  skim.
- [ ] Fix every confirmed high/medium finding with a new failing regression test,
  focused verification, and a separate review-fix commit. Re-run the relevant
  reviewer until no high/medium finding remains.
- [ ] Run the complete local gate from the remediation worktree:

```bash
cd /Users/amattas/GitHub/aviato/.worktrees/onboarding-readiness-remediation
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
python -m aviato.cli validate
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
python scripts/regen-templates.py --check
git diff --check
git status --short --branch
```

- [ ] Repeat the exact relative yamllint/strict validation behavior with an
  ignored synthetic `.worktrees/sibling` containing invalid YAML, as in Task 20,
  and then remove it. Build wheel+sdist into a fresh directory, inspect both
  metadata files, install the wheel into a clean CPython 3.12 environment, and
  run `aviato --help`.

```bash
tmp_root="${TMPDIR:-/tmp}"
verify_root="$(mktemp -d "${tmp_root%/}/aviato-cpython312.XXXXXX")"
trap 'rm -rf -- "$verify_root"' EXIT
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
python -m build --no-isolation --outdir "$verify_root/dist"
uv venv --python 3.12 "$verify_root/venv"
set -- "$verify_root"/dist/*.whl
[ "$#" -eq 1 ]
wheel="$1"
uv pip install --python "$verify_root/venv/bin/python" "$wheel"
(cd "$verify_root" && "$verify_root/venv/bin/python" -I -c 'import importlib.metadata, sys, aviato; assert sys.version_info[:2] == (3, 12); assert importlib.metadata.version("aviato") == aviato.__version__')
(cd "$verify_root" && "$verify_root/venv/bin/aviato" --help)
```

Expected: `uv` provisions CPython 3.12 if absent, exactly one wheel installs with
no source checkout on `sys.path`, import succeeds under 3.12, and the console
entry point exits zero.
- [ ] Confirm the only expected unclosed local row is OR-022 external proof (plus
  any honestly unavailable platform capability such as required tag pattern).
  Do not call local implementation “onboarding ready” and do not count synthetic
  evidence fixtures as proof.
- [ ] Commit only actual review fixes or durable traceability corrections. A
  verification-only task does not need an empty commit.

## Wave 8: External release and evidence — separately authorized checkpoints

Everything below is intentionally blocked until the preceding local gate is
green and the user gives the named explicit approval. No earlier approval is
standing authorization for these mutations.

### Task 26: Publish the feature-bearing Aviato release

**External checkpoint A — approval required before the first push/PR mutation.**

**Files:**

- Verify: `pyproject.toml`
- Verify: `.github/workflows/reusable-release.yml`
- Verify: `.github/workflows/reusable-pypi-publish.yml`
- Verify: `.github/workflows/aviato-protection-checkpoint.yml`
- Verify/update after proof: `docs/evidence/rollout/2026-07-14-aviato.yml`
- Verify/update after proof: `docs/requirements/traceability.md`

- [ ] Read and use `superpowers:finishing-a-development-branch`. Present the
  verified branch state and request explicit authorization before pushing,
  opening a remediation PR, changing any live setting, merging, tagging, or
  publishing.
- [ ] After approval, push only this branch, open the remediation PR, and let the
  normal protected CI/security path run. Resolve review findings on the branch;
  do not use an administrative bypass unless separately and specifically
  authorized.
- [ ] Request a fresh merge checkpoint when the protected PR is green. After the
  normal remediation merge, derive the next version with Aviato's versioning
  command and use the ordinary protected release proposal path. Review and merge
  that proposal normally under a separate merge checkpoint; then record the
  exact resulting default-branch SHA and intended tag before any tag exists.
- [ ] Before the root repository can release under the hardened gate, request
  explicit approval to preview/configure/read back its composite protection and
  every privileged environment derived by the root `DesiredState`—at minimum
  `release` and `pypi` if both remain in the compiled graph—with concrete user
  reviewers, exact branch/tag policies, self-review prevention, and the required
  manual UI step wherever `can_admins_bypass` is not false. Recompute/reconfirm
  after any UI change and require the root `doctor` plus final convergence
  readback for the complete environment set to be green.
- [ ] With the intended tag and final merged SHA fixed, run the root
  `aviato release-checkpoint collect` locally, have the distinct concrete user
  reviewer run credential-free `review-sign`, and have the receipt-bound
  submitter dispatch the generated trusted-default-branch
  `.github/workflows/aviato-protection-checkpoint.yml`. Verify the exact
  signed/attested receipt and current no-bypass environment readback. Request a
  fresh publishing checkpoint only then; create the tag through the normal path
  and require the release gate plus every privileged job to consume that exact
  checkpoint digest. Any ref/SHA/actor/reviewer/environment drift invalidates it
  and sends the flow back to preview/collection rather than publishing. Here the
  "normal path" is the generated root `.github/workflows/aviato-ci.yml` closed
  promotion dispatch with those exact bound inputs; the merge-triggered run is
  never the promotion path.
- [ ] Preserve `0.3.0`, tags `0.3.0`/historical run artifacts, and the failed
  post-upload confirmation unchanged. For the new release, record exact merge,
  tag, release workflow/job, PyPI wheel/sdist/manifest/attestation digests,
  successful confirmation, and clean isolated installation.
- [ ] Re-run the local evidence and traceability tests after recording only
  redacted durable facts. The exact published release version/tag (`X.Y.Z`), not
  a raw commit SHA, becomes the common declaration pin for every Task 27
  consumer. Record and compare its separately resolved immutable commit SHA in
  every operation/evidence row.

### Task 27: Prove all five profiles and target identity chains

**External checkpoint B — approval required before any proof repository,
setting, protection, environment, publisher, package, site, or TestFlight
mutation.**

**Files:**

- Create after proof: `docs/evidence/onboarding-readiness/releases/<release>.yml`
- Create after proof: `docs/evidence/onboarding-readiness/releases/<release>.snapshot.json`
- Create after proof: `docs/evidence/onboarding-readiness/releases/<release>.live-receipt.json`
- Create after proof: `docs/evidence/onboarding-readiness/releases/<release>.review-envelope.json`
- Create after proof: `docs/evidence/onboarding-readiness/releases/<release>.review-envelope.sig`
- Modify after proof: `docs/requirements/traceability.md`
- Modify after proof: applicable module backlogs only

- [ ] Ask for explicit authorization to create and mutate the four disposable
  public synthetic repositories and to select/use an existing viable iOS target.
  Confirm names at the checkpoint; the currently planned synthetic set is:

```text
amattas/aviato-proof-python-library-20260713
amattas/aviato-proof-python-service-20260713
amattas/aviato-proof-node-service-20260713
amattas/aviato-proof-python-component-20260713
```

If no viable/authorized iOS target exists, retain Swift, OR-022, and all dependent
aggregate rows as blocked and explicitly report that the overall goal is not
complete.

- [ ] Before each mutation, capture repository ID/slug/default branch/head/dirty
  state, declaration/seed/inventory paths, classic/security/merge settings,
  environments/checks, and full branch/tag rulesets with Task 23's runbook.
- [ ] Designate the first synthetic repository as the disposable onboarding
  pilot. Before touching the remaining repositories or the existing iOS target,
  run preview, temporary-clone transition, proposal/exact-SHA CI, protected
  merge/default-branch exact-SHA CI, protection, readback, doctor, and the local
  journal interruption/recovery drill. Stop for
  a separate action-specific restoration/rollback approval before exercising any
  live protection or hosted-artifact recovery, then prove that restoration and
  re-onboarding converge. A failed pilot halts the rest of the matrix.
- [ ] Onboard each target with the exact Task 26 release. Review the pinned
  transition preview, execute in a temporary clone, create the reviewable
  proposal, and prove exact proposal-SHA CI/security. Request a separate explicit
  merge approval for that target, merge through its normal protected path, and
  record the resulting default-branch SHA. Re-run exact-SHA CI/security and a
  fresh pinned transition/idempotence preview against that merged state; the
  pre-merge context, plan IDs, and checks are no longer applicable.
- [ ] Only after the generated checkpoint workflow exists on the current default
  branch, reconstruct `OperationContext` and the composite protection plan from
  that exact merged SHA. Obtain the separate reviewer/environment authorization,
  resolve concrete reviewer/team IDs and deployment-ref policy, include them in
  the confirmed plan, and apply/read back every surface. If the approved manual
  UI step is needed to disable administrator bypass, perform it, then recompute
  and reconfirm the entire plan against fresh state before requiring
  `can_admins_bypass == false` and `doctor` exit zero. A platform-rejected
  required tag pattern remains a failed row, not a warning-only pass.
- [ ] Obtain separate user action/approval before registering the TestPyPI trusted
  publisher; configuring or changing concrete managed/starter release, App
  Store environment reviewers/policies/credentials, including manually
  disabling administrator bypass where the API cannot write it; running
  operator-local live
  evidence collection with GitHub/App Store credentials; submitting signed
  sanitized evidence to the no-secret verifier workflow;
  publishing to TestPyPI/GHCR/Pages; or uploading to App Store
  Connect/TestFlight.
- [ ] For every managed matrix target, after full protection/readback and before
  creating its release tag, run `aviato release-checkpoint collect` locally,
  have the distinct concrete user reviewer run credential-free `review-sign`,
  have the bound submitter dispatch the generated consumer checkpoint intake,
  verify its attested receipt, and require the managed release gate to carry
  that exact digest through every privileged job. Never copy the collector
  credential or reviewer key into GitHub. Run the separate starter checkpoint
  ceremony only if an actual starter-kit consumer is included in proof; it does
  not substitute for any managed profile checkpoint.
- [ ] Prove and record the entire approved matrix:

  - `python-library`: transition/protection/doctor, real CI/security/release,
    TestPyPI frozen-manifest files/digests/attestations/clean install, and current
    supported versioned Pages branch/tree/artifact/served identity.
  - `python-service`: transition/protection/doctor, real CI/security/release,
    multi-architecture GHCR child/index/alias digests, scan binding,
    SBOM/provenance.
  - `node-service`: transition/protection/doctor, real Node CI/security/release,
    and the same GHCR identity chain.
  - `python-component`: transition/protection/doctor, real zero-deployment
    CI/security/release, and proof that no deployment mutation path ran.
  - `swift-app`: transition/protection/doctor, protected environment approval,
    build/upload job, App Store delivery/build identity, and processed TestFlight
    receipt.

- [ ] Populate the release manifest only from durable URLs, IDs, SHAs, digests,
  conclusions, signed/attested receipts, and redacted state. Run the real
  authenticated `--verify-live` validator locally, write the exact manifest,
  sanitized snapshot, and live-receipt paths from Task 24, then have the distinct
  authorized reviewer produce the exact review envelope and detached signature.
  Any failed, unknown, missing,
  unauthenticated, nonexistent, stale, or unbound row returns nonzero and retains
  its backlog; schema-only success is never closure.
- [ ] Create a fresh local evidence branch from the current trusted default
  branch, stage exactly those five redacted files, and commit them. Request
  explicit authorization before pushing that evidence branch. After push, record
  its immutable commit SHA and dispatch the trusted default-branch verifier with
  only that SHA and strict release identifier. Require successful
  `--verify-snapshot` comparison, exact trusted workflow/run/attempt identity,
  and the final receipt attestation before treating this proof snapshot as
  closure evidence; never dispatch against an uncommitted working tree or paths
  supplied by the caller.

### Task 28: Exercise rollback, reconcile evidence, and clean up only when approved

**External checkpoint C — approval required before yank/delete/restore/rollback,
expiration, repository cleanup, evidence PR, or merge.**

**Files:**

- Modify: `docs/evidence/onboarding-readiness/releases/<release>.yml`
- Modify: `docs/evidence/onboarding-readiness/releases/<release>.snapshot.json`
- Modify: `docs/evidence/onboarding-readiness/releases/<release>.live-receipt.json`
- Modify: `docs/evidence/onboarding-readiness/releases/<release>.review-envelope.json`
- Modify: `docs/evidence/onboarding-readiness/releases/<release>.review-envelope.sig`
- Modify: `docs/evidence/rollout/2026-07-14-aviato.yml`
- Modify: `docs/requirements/traceability.md`
- Modify: proven module backlogs
- Delete only after full promotion: temporary superseded superpowers design/plan

- [ ] Request explicit authorization for each destructive or externally visible
  recovery action. Exercise the approved target-specific recovery contract on
  disposable artifacts: TestPyPI yank/restore evidence, GHCR alias/delete or
  equivalent rollback, Pages branch/site restoration, TestFlight expiration or
  approved cleanup, and protection restoration from the captured semantic
  snapshot. Preserve evidence before cleanup.
- [ ] After the last approved recovery mutation, update the manifest and rerun
  `scripts/verify-onboarding-evidence.py --verify-live` locally. Replace all four
  redacted sidecars with the new snapshot/live receipt/distinct-reviewer signed
  envelope and signature. The Task 27 attestation cannot cover changed cleanup
  state or a new receipt digest. Commit exactly the refreshed five-file set to a
  new immutable evidence commit, request explicit push authorization, dispatch
  the trusted default-branch verifier with that commit/release ID, and require a
  new successful comparison and final receipt attestation before reconciliation.
  Bind that new receipt in traceability. Update a leaf or aggregate row only when
  every dependency validates authoritatively; failed or unavailable cleanup/
  proof remains open.
- [ ] Put evidence reconciliation on a fresh review branch, run the full local
  gate, retain the immutable verified evidence commit as an ancestor, request
  review, and obtain separate approval before push/PR/merge. Any edit to one of
  the five verified evidence files invalidates the attestation and requires the
  collection/sign/dispatch cycle again. Do not
  retroactively edit the feature-bearing release or historical `0.3.0` evidence.
- [ ] Only after every row validates, promote all remaining durable decisions to
  living requirements/security/runbook owners, mark OR-022 verified, and prune
  this temporary design/plan in the separately reviewed reconciliation change.
  If Apple or any platform requirement remains unavailable, keep the temporary
  closure ledger and owning backlogs, report the exact blocker, and do not mark
  the overall goal complete.

## Final acceptance audit

Before the final completion claim, read and use
`superpowers:verification-before-completion` and
`superpowers:finishing-a-development-branch`, then prove all of the following
from fresh output:

1. OR-001 through OR-021 have current implementation, behavioral tests, and
   canonical traceability; OR-022 has a validator-successful real five-profile
   release manifest.
2. Every consumer command uses one pinned snapshot and canonical Git root; no
   installed Library data is substituted for a declared pin.
3. Pipeline removal removes executable jobs/triggers/privileges/checks and clean
   obsolete artifacts, while untrusted state blocks.
4. Local and proposal onboarding converge to the same declaration, sidecar,
   inventory, artifacts, and deletions through a recoverable transaction.
5. Complete protection covers classic/security/merge/ruleset/environment/check
   surfaces and never mislabels degraded, partial, or indeterminate state.
6. Ruleset plans bind identity, pin, snapshot, conditions, live IDs, and payloads;
   changed or uninspectable state cannot apply.
7. `doctor` returns zero only for the complete all-positive readiness vector.
8. Managed and starter privileged publishers perform no untrusted computation
   and preserve byte identity through remote readback.
9. The full test suite, `aviato validate`, strict local gate, generation parity,
   package build/metadata/install, and independent code review are green.
10. The onboarding pilot, full target matrix, rollback, and cleanup evidence are
    durable, redacted, and validated—or the goal remains explicitly blocked.
