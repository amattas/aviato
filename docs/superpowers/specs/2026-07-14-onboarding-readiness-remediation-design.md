# Onboarding Readiness Remediation Design

**Status:** Approved by the user on 2026-07-14  
**Date:** 2026-07-14  
**Scope:** Managed Aviato engine, vendored starter kit, release verification,
operator readiness, and the evidence required before repository onboarding is
declared safe

## Objective

Fix every finding from the onboarding-readiness review and prove that Aviato can
begin onboarding repositories without stamping one Library version while using
another, silently retaining removed automation, clobbering operator files,
reporting incomplete protection as success, or exposing publishing credentials
to consumer-controlled computation.

This design uses the controlled-rollout boundary approved for the remediation:

- all repository-controlled code, test, workflow, configuration, and living
  documentation fixes are in scope;
- low-risk GitHub readback and disposable-consumer proof may follow repository
  verification;
- protected merges, production releases, registry publication, TestFlight,
  rollback/destructive actions, and cleanup remain explicit checkpoints;
- no external state is evidence merely because a local test predicts it.

Completion is requirement-by-requirement. A green narrow test, a plausible
workflow, or an absence of newly observed failures is not sufficient.

## Relationship to the backlog-closure design

The unmerged `codex/backlog-closure-sprint-design` branch contains an approved
broader design for documentation restructuring, publication controls, Apple
contract changes, release verification, and external target proof. This
remediation imports only its relevant contracts:

- the immutable PyPI distribution-manifest design;
- fail-closed external evidence and target-by-target closure;
- preservation of the historical `0.3.0` upload and failed post-publish
  confirmation as immutable evidence;
- explicit authority checkpoints before external mutations.

Unrelated documentation hierarchy, selector/catalog, and Apple-contract work is
not silently pulled into this branch. If those efforts later converge, their
plans must reconcile overlapping files and retain the stable closure IDs below.

## Normative decisions changed by this remediation

The review exposed contradictions in the current requirements, so the
implementation must update the living owners explicitly rather than hiding the
new behavior in code or this temporary design:

- the workflow/scaffold module model gains a data-driven workflow-envelope and
  pipeline-fragment interface because the current independent bundles cannot make
  pipeline removal affect executable automation;
- a marker-bearing `.github/aviato.managed.yml` is generated engine state, not a
  seed-once/operator-owned non-annotatable file;
- unmanaged/dirty/foreign collisions are enumerated during onboarding preflight
  and block proposal creation, replacing §5.2's unsafe implication that an
  incomplete proposal may still be opened and merged;
- `complete-protection`, provision, and ruleset remediation share one
  preview/confirmation contract instead of treating only standalone ruleset
  apply as reviewed;
- an explicitly unsupported `tag_name_pattern` remains a visible, non-ready
  capability gap; workflow grammar and immutable tags reduce publication risk
  but cannot pretend they prevented malformed tag creation;
- every OR-ID is mapped into the canonical requirements/control traceability
  matrix and relevant module backlog before this design is pruned.

These are reviewed contract changes, not compatibility accidents. The
implementation plan must name each living document and test that changes with
them.

Specifically, `docs/requirements/core/structure.md` §3.2,
`docs/requirements/core/modularity.md` §§4.1/5.1, and
`docs/specifications/modules/scaffolding/sync.md` are updated to define the new
module fields, pipeline-conditioned template resolution, and resulting fully
resolved set. The requirements index/diagrams and architecture documentation
change in the same commit as the implementation; the new abstraction cannot live
only in Python dataclasses.

## Readiness definition

Aviato is ready to start onboarding only when all of the following are true:

1. Every consumer operation resolves desired state from the exact declared
   Library snapshot and exposes the immutable commit it used.
2. Pipeline composition controls executable automation, permissions,
   environments, artifacts, and required checks—not metadata alone.
3. Onboarding and sync are conflict-preflighted, preserve operator-owned state,
   retire only provably clean obsolete managed state, and never report partial
   adoption as success.
4. Full protection means classic settings, security/merge settings, and named
   branch/tag rulesets have all been applied or their partial/degraded state is
   explicit and recoverable.
5. Ruleset preview is a semantic, target-bound, version-bound plan whose identity
   must still match immediately before apply.
6. `doctor` succeeds only when every applicable local and remote readiness signal
   is positively healthy.
7. No checked-out or consumer-controlled build step executes in a job holding a
   publishing, registry, Pages, release, or OIDC credential.
8. Repository gates, runbooks, package metadata, living documentation, and live
   evidence tell the same current-state story.

## Finding closure ledger

| ID | Finding | Required closure |
|---|---|---|
| OR-001 | Onboard/provision and other consumer paths render the installed Library while stamping the requested pin. | Resolve one exact pinned snapshot and inject it into every consumer-facing operation. |
| OR-002 | Library tag API failures are collapsed into “not found,” permitting fallback to a same-named mutable branch. | Distinguish found, definite 404, and operational/error responses; only a tag 404 may fall back to a branch. |
| OR-003 | Pipeline removal changes metadata/status checks but leaves executable jobs in monolithic callers. | Make pipelines own renderable workflow jobs and dependencies; compile callers from the selected graph. |
| OR-004 | Sync/diagnosis cannot discover and retire formerly managed artifacts. | Maintain a derived managed inventory; delete only obsolete artifacts whose marker and live body prove clean ownership. |
| OR-005 | Fresh `onboard --open-pr` proposals omit `.github/aviato.seed.json`. | Execute the same transition in the proposal clone so sidecar additions and baselines are staged. |
| OR-006 | Remote onboarding overwrites unmanaged paths; local onboarding can skip conflicts, write a declaration, and return success. | Shared preflight; unmanaged/dirty/foreign conflicts block mutation/proposal and success requires full desired-state convergence. |
| OR-007 | No command completes both classic settings/security toggles and named rulesets; provision can claim “full protection” without rulesets. | One composite, idempotent protection plan powers provision and `complete-protection`. |
| OR-008 | `doctor` prints failed/unknown prerequisites but exits zero when drift automation alone is healthy. | Aggregate every applicable readiness signal; `False` and `None` are non-ready. |
| OR-009 | Ruleset dry-run lacks a semantic diff; declaration mode is not bound to slug/pin; conditions are omitted from drift. | Full live-to-desired plan, plan digest confirmation, slug/version binding, and fail-closed condition comparison. |
| OR-010 | Re-onboarding can clear `bootstrap`. | Preserve bootstrap only for a structurally verified Library and reject it elsewhere before rendering. |
| OR-011 | Relative/macOS-aliased targets can crash after writes, and nested repository directories are accepted. | Canonicalize once before mutation and require the canonical target to equal the Git root. |
| OR-012 | Unknown `--var` keys are silently ignored, including preview paths. | Closed-set key validation and typed partial resolution for previews. |
| OR-013 | PyPI confirmation hashes publisher-created `.publish.attestation` sidecars and reports a successful upload as failed. | Freeze and validate an unprivileged distribution manifest; confirm only its exact filenames and digests. |
| OR-014 | Starter publishing workflows execute arbitrary tagged source in privileged jobs. | Read-only build/scan jobs hand immutable, verified artifacts to isolated publish/release jobs with no checkout or consumer command. |
| OR-015 | Starter branch protection has a standing admin bypass, weak review settings, non-strict checks, and an immediate-mutating installer. | Apply the one-baseline security posture; dry-run semantic installer with explicit confirmation and separate tag-creation authorization from immutable tags. |
| OR-016 | Reconcile/ruleset mutation has per-surface TOCTOU exposure and unavoidable partial cross-API behavior. | Re-read and fingerprint each surface immediately before its write; report completed/failed/unattempted operations and retain idempotent recovery. |
| OR-017 | Non-gating zizmor findings disappear, while the supply-chain specification promises stronger order-aware behavior than the accepted implementation. | Surface warnings without gating; correct the specification while preserving explicitly frozen verifier and `dangerous-triggers` decisions. |
| OR-018 | Strict local validation recursively lints sibling `.worktrees` and fails for unrelated generated copies. | Exclude `.worktrees/**` in yamllint and prove the actual relative invocation ignores them. |
| OR-019 | Rollout plans, backlogs, traceability, and tests describe stale PR/release/security state. | Promote durable facts, keep genuine blockers open, and replace token-presence assertions with semantic state assertions. |
| OR-020 | No complete onboarding snapshot/abort/recovery/protection-restoration runbook exists. | Add and test a staged pilot runbook covering pre-mutation capture, abort criteria, partial recovery, and settings restoration. |
| OR-021 | The published package lacks README/long-description metadata. | Declare the README and inspect built wheel/sdist metadata. |
| OR-022 | Local/static checks do not prove real onboarding, protection, or deployment behavior. | Run a release-scoped, target-specific external evidence matrix; close only the rows actually proven. |

## Architecture

### 1. Pinned operation context

Every consumer operation begins by constructing an `OperationContext`:

```text
OperationContext
├── canonical repository root
├── existing declaration (when present)
├── declared Library pin
├── resolved ref kind and immutable commit SHA
├── LibrarySnapshot
│   ├── Registry
│   ├── ruleset/policy root
│   └── temporary archive lifetime
├── running tool version
└── structurally validated bootstrap state
```

The snapshot is resolved exactly once per operation. Floating branch or major
references therefore cannot move between profile resolution, template rendering,
ruleset rendering, diagnosis, and application. Repin and profile migration may
carry both the old and target snapshots so removed artifacts remain discoverable.

There are exactly two snapshot sources:

- **Published consumer snapshot:** first prove that the Library repository is
  accessible under the current authentication context, resolve the declared ref
  to an immutable commit, download the archive **by that commit SHA**, verify the
  archive root/layout and extracted content identity, and use only its Registry
  and policy root for the operation.
- **Bootstrap snapshot:** permitted only when the operated canonical target is a
  structurally verified Library checkout. It uses that checkout's local
  `aviato/library` tree, never the installed package tree, and records the local
  Git HEAD plus a deterministic Library-tree content digest. It does not require
  a published ref, preserving the self-reference bootstrap contract.

No pin-bearing consumer path may read `MODULE_SOURCE_ROOT` or
`POLICY_DATA_ROOT` after the context is constructed. Installed roots remain
valid only for validation of the installed/source package itself; they are never
substitutes for the operated bootstrap checkout.

#### Ref-resolution result

GitHub reads have three semantic outcomes:

- **FOUND:** validated object type and 40-character commit/tag object SHA;
- **NOT_FOUND:** a correlated HTTP 404 for the exact endpoint after repository
  accessibility and authentication context were positively established;
- **ERROR:** authentication, authorization, rate limit, timeout, network, 5xx,
  malformed response, or any other unclassified failure.

A tag wins when both a tag and branch share a name. Only a tag `NOT_FOUND`
permits branch lookup. Annotated-tag peel failure is always an error and never a
reason to try a branch. Operator output identifies the chosen ref kind and
resolved commit. A hidden/private repository, stale authentication, or ambiguous
404 is an error rather than evidence that the tag is absent. Tests move the ref
between lookup and archive fetch and prove that the archive still comes from the
original resolved commit.

### 2. Desired-state compiler

The compiler transforms the pinned snapshot plus the declaration and resolved
non-secret variables into one immutable `DesiredState`:

```text
DesiredState
├── managed and seed-once artifacts
├── workflow groups and rendered jobs
├── protected settings
├── named rulesets
├── protected environments
├── required status checks
└── local and remote prerequisite probes
```

This eliminates independent calculations that can disagree about pipelines,
workflow jobs, status checks, environments, or rulesets.

#### Pipeline-owned workflow graph

Pipeline modules gain data-only ownership metadata:

- stable pipeline and job identities;
- one workflow-envelope reference (for example a CI or docs caller);
- trigger contributions owned by the pipeline;
- renderable job fragment references;
- required pipeline/job dependencies;
- owned non-workflow artifact references;
- job permissions, inputs, secrets, runner, and optional environment;
- produced status-check identity;
- the existing always-on invariant.

A `WorkflowEnvelopeModule` is a new data module referenced by pipeline modules
that remain selected through the existing workflows bundle. It owns only shared
Actions structure such as name,
concurrency, and empty/read-only top-level permissions. Selected pipelines
contribute triggers as well as jobs; trigger maps are deep-merged with explicit
list add/remove semantics and conflicts fail. A removed tag/schedule pipeline
therefore cannot leave its trigger running unrelated jobs. The compiler renders
selected fragments, merges their YAML ASTs deterministically, and emits one
managed caller for each nonempty envelope.

Compilation fails before output when it observes:

- duplicate job IDs or artifact paths;
- a `needs` edge to an absent job;
- a missing required pipeline dependency;
- incompatible or orphaned trigger contributions;
- incompatible permissions, inputs, secrets, or environment definitions;
- a declared status check not produced by the rendered workflow;
- a removed always-on pipeline;
- a workflow-level privilege broader than the selected graph requires.

Removing a pipeline therefore removes executable jobs and their privilege
surface. Removing the last owner of an artifact omits that artifact from desired
state. Adding a capability remains data work—adding modules and references—rather
than editing core behavior for a target name.

Pipeline-owned non-workflow artifacts are references to existing
`TemplateModule` identities, not a second raw artifact format. Fully resolved
templates are the explicit union of scaffold-bundle base templates and template
modules referenced by selected pipelines, with the existing add/remove and
collision rules applied.

Generated YAML is deterministic. The compiler never parses and rewrites an
operator-owned workflow.

#### Partial preview variables

An exact `DesiredState` and every mutation require complete typed variable
resolution. A fresh read-only preview may instead produce a
`PartialDesiredState`: supplied keys are closed-set validated and coerced, absent
values are represented as `Unknown`, and each `when` expression evaluates to
true, false, or indeterminate. Definite artifacts/settings are listed normally;
potential artifacts, environments, checks, and missing variables are listed as
conditional/indeterminate. A partial preview never emits a confirmation plan ID
and can never be applied. This prevents an unknown variant from being silently
excluded while preserving useful pre-configuration guidance.

### 3. Managed inventory and retirement

`.github/aviato.managed.yml` is an annotatable, marker-bearing, generated,
schema-versioned index of the last successfully applied desired state. It is not
seed-once, and its marker makes manual modification visible under the same
ownership rules as every other managed YAML artifact. Its body contains:

- profile and stable profile identity;
- declared pin and resolved Library commit;
- output path to stable artifact ID;
- owning pipeline IDs;
- expected marker/body/input hashes;
- explicit legacy path aliases used during reviewed migrations;
- an `owned_remote_resources.rulesets` section containing each desired stable
  `(name, target)` identity, source snapshot commit, and canonical desired payload
  fingerprint.

The inventory does not recursively list itself. The scanner treats its canonical
path as the one distinguished engine-state artifact, validates its own marker
and body separately, and excludes it from ordinary entry reconciliation. Managed
markers remain the source of truth for whether other files are managed; the
inventory is an index for discovering prior paths and never authorizes deletion
by itself.

An obsolete path may be deleted only when all of these are true:

1. the reconciled prior inventory/marker universe maps that path to a known
   artifact identity or an unambiguous legacy artifact identity;
2. its first nonblank line is a valid Aviato marker;
3. the marker belongs to the current profile or an explicitly authorized source
   profile during migration;
4. the marker records a known version;
5. the live body still equals the marker hash.

Modified, malformed, foreign, unreadable, symlink-substituted, or unmanaged
paths block the transition and remain untouched. Missing obsolete files are
removed from the next inventory. Seed-once outputs remain operator-owned and are
never retired through this mechanism.

Every transition plan and doctor run performs a confined marker-universe scan
over tracked plus untracked nonignored files reported by Git, excluding nested
metadata/worktree/build roots. It reconciles that universe with the inventory
and desired state. A missing, partial, malformed, hand-edited, or adversarial
inventory can therefore never hide a stale marked workflow. Any inventory/marker
mismatch is classified explicitly; unambiguous legacy markers may be adopted
into a reconstructed inventory, while ambiguity fails closed and requires an
explicit operator rebaseline. Tests cover absent, truncated, malformed,
manually edited, and path-injection inventories as well as marked files omitted
from an otherwise valid inventory.

### 4. Transition plan and executor

Local onboarding, proposal onboarding, sync, repin, and profile migration share
one planning model. A `TransitionPlan` contains:

- canonical root, snapshot SHA, declaration identity, and plan digest;
- desired writes with complete replacement bytes and preserved file modes;
- clean obsolete deletions;
- seed additions and preserved seed records;
- declaration, seed-sidecar, and managed-inventory updates;
- expected pre-mutation fingerprints for every affected path;
- blocking conflicts and nonblocking operator notices;
- deterministic operation order and structured completed, failed,
  indeterminate, and unattempted outcomes.

Planning performs no mutation. Unknown seed integrity, a conflicting managed
target, an untrusted obsolete path, or a noncanonical repository root prevents
execution.

Immediately before execution, every planned path is re-confined and its
fingerprint is rechecked. Writes retain atomic per-file replacement and line
ending/mode guarantees; deletion is allowed only after the same ownership check
passes again.

Multi-file execution uses a private transaction journal and staged preimages in
the repository's Git metadata path (never a tracked consumer path). Managed
artifacts/deletions are applied in deterministic order, the seed sidecar and
declaration follow, and the marker-bearing managed inventory is the final commit
record. The journal records each completed operation before advancing. A final
diagnosis must match desired state before the inventory is accepted and the
journal is removed.

An ordinary exception triggers rollback from staged preimages and semantic
verification. A process interruption leaves the journal and backups; doctor is
non-ready while either exists. Rerunning the same plan may resume only when every
path still equals its recorded preimage or desired fingerprint. A different plan
must first use explicit journal recovery/rollback. Any path matching neither
state is a conflict. Fault-injection tests interrupt every operation boundary,
including state-file and deletion failures, and prove convergence or an honest
recoverable partial state. The command never reports success merely because its
last attempted write returned.

`--allow-dirty` may tolerate unrelated worktree changes but never an overlap with
a planned path.

#### Proposal path

Proposal onboarding clones the target, builds and executes the same transition,
then passes the resulting worktree diff to the worktree proposal mechanism. This
captures additions, seed-sidecar baselines, inventory changes, and deletions.

Existing seed-once files are preserved and enumerated in the proposal body.
Unmanaged, dirty, malformed, or foreign collisions are blocking preflight errors;
the command enumerates them before proposal creation and does not create a
mergeable partial-adoption proposal. Living §5.2 onboarding requirements and its
diagram are updated to make this safer ordering normative.

### 5. Composite protection plan

A `ProtectionPlan` is derived from the same pinned `DesiredState` and contains:

- immutable GitHub repository node/database identity, slug, and default branch;
- classic default-branch protection;
- repository security toggles;
- repository merge-method settings;
- full named branch/tag ruleset payloads;
- expected protected environments and status checks;
- semantic before/after state and per-surface fingerprints.

Standalone apply, `complete-protection`, and staged provision all use one
composite preview/confirmation identity. Dry-run is the default. Mutation
requires `--apply --confirm <plan-id>` (or the equivalent explicit confirmation
captured by the interactive provision operation), then recomputes repository
identity, target, default branch, pinned snapshot, declaration, and every live
surface. Provision is not complete until every required surface succeeds.

Every write is followed by full semantic readback. Outcomes are `completed`,
`degraded`, `failed`, `indeterminate`, or `unattempted`; a timeout/connection loss
after submission is indeterminate until readback proves the desired state. An
indeterminate result is never blindly retried and never reported as failure or
success. Recovery starts with a fresh preview and confirmation. Rerunning
`complete-protection` is idempotent only after that current-state binding.

The narrowly correlated unsupported `tag_name_pattern` 422 remains the only
allowed degradation. It is visible and remains non-clean in diagnosis/drift.
Authorized release-tag creation, no-bypass tag immutability, fail-closed workflow
grammar, default-branch ancestry, and exact-SHA CI reduce exploitation impact but
do not prevent a malformed immutable tag from being created and therefore are
not called equivalent. Repositories on a tier that rejects the rule remain not
ready until the capability exists or the user separately approves a changed
requirement.

### 6. Ruleset semantic plan and confirmation

Declaration-aware ruleset mode accepts exactly one repository. It derives the
canonical slug from the declaration checkout's GitHub remote and rejects a
supplied mismatch or an uninspectable/non-GitHub remote. It uses the pinned
snapshot and performs the existing version-compatibility gate before planning.

The binding fetches full live rulesets, not list summaries. Canonical plan data
includes:

```text
schema version
repository node/database ID, slug, and resolved default branch
tool version, declaration pin, and snapshot commit
operations keyed by (name, target)
  action: create | update | delete | noop
  selected live ruleset ID (for update/delete)
  canonical before payload and fingerprint
  canonical desired payload
  field-level semantic changes
plan_id = SHA-256(all security-relevant canonical fields)
```

Timestamps, URLs, and source display objects are excluded. The immutable
repository ID, selected live ruleset ID, enforcement, conditions, bypass actors,
rule types, and every rule parameter are included because they bind the write
target. Duplicate desired or live `(name, target)` identities fail closed.

Dry-run prints this plan and its ID. `--apply` requires
`--confirm <plan-id>`, recomputes immediately, and refuses if identity changed.
Before each sequential create/update/delete it re-reads repository identity,
default branch, namespace presence, exact ruleset ID, and full before
fingerprint. A named ruleset absent from desired state may be deleted only when
the prior valid managed inventory claims that remote identity, its recorded
source snapshot renders the same prior fingerprint, and the live payload still
matches it exactly. The confirmed apply/readback receipt in the Consumer's
tracking issue must also bind repository ID, ruleset ID, plan ID, and payload
fingerprint; without that receipt, retirement remains an explicit manual action.
Otherwise deletion is a conflict. Each write receives full-detail post-write readback. Cross-API
transactionality is unavailable, so a later failure never triggers a risky
synthetic rollback; every completed, degraded, failed, indeterminate, and
unattempted operation is reported precisely.

#### Condition normalization

`conditions.ref_name.include` and `exclude` must be string arrays. Comparison is
set-based after sorting/deduplication while preserving pattern bytes and case.
Known equivalences are normalized with repository metadata:

- branch `~DEFAULT_BRANCH` is equivalent to the exact current default-branch ref;
- target-appropriate `~ALL` is equivalent to all refs of that target.

Undocumented wildcard transformations are not guessed. Unknown keys, malformed
shapes, or an unrecognized platform normalization are **indeterminate**, and
doctor/settings drift treat indeterminate as non-clean.

### 7. Readiness diagnosis

`DiagnosisReport.readiness_healthy` is true only when:

- every expected managed artifact is `clean`;
- no expected artifact is missing, mergeable-drift, or dirty-drift;
- the managed inventory marker/body/schema are valid and its entries exactly
  reconcile with the full marker universe;
- no obsolete marked artifact is unclassified, still executable, or awaiting
  safe retirement;
- no transition journal or staged recovery state remains;
- seed integrity has no divergence or unknown state;
- no secret-typed variable is persisted;
- local and remote drift automation are proven present and enabled;
- every applicable local prerequisite is true;
- every applicable remote prerequisite is true;
- issue-channel availability is true;
- the current-head security heartbeat is true;
- ruleset condition comparison and full protection are clean, with no unsupported
  required rule;
- no remote mutation/readback result is indeterminate.

`False` and `None` both mean not ready. `doctor` returns `0` only for healthy,
`1` for unhealthy/unknown, and `2` for malformed configuration or an operator
usage error. `--no-remote-probe` is reporting-only and remains nonzero because
remote readiness was not proven.

### 8. Release and promotion security

#### Immutable distribution manifest

The unprivileged reusable build emits a schema-versioned JSON manifest containing
only normalized distribution basenames, sizes, and SHA-256 digests. The manifest
lives outside `dist`/the publisher `packages-dir` and is never itself attested or
uploaded as a distribution. Generation and validation require confined regular
non-symlink files, canonical safe basenames, an exact allowed wheel/sdist type
set, valid lowercase digest/size fields, uniqueness, and a nonempty set. They
reject directories, device/special files, symlinks, traversal, malformed schema,
and unsupported types.

The consumer-local privileged publisher:

1. downloads the immutable build artifact;
2. validates manifest schema and uniqueness;
3. proves every manifested distribution exists and matches size/digest;
4. rejects an unmanifested distribution before invoking any OIDC/attestation or
   publisher action;
5. attests and publishes;
6. confirms only the manifested distributions against PEP 691.

Publisher-created `.publish.attestation` sidecars cannot expand the expected set.
Missing, mutated, duplicate, traversing, or unlisted distributions fail before
publication. Tests also cover symlink, directory, malformed digest/size/schema,
manifest-placement, and post-attestation-sidecar cases. Tests execute the real
confirmation script rather than checking workflow strings.

The historical `0.3.0` artifacts are not republished or rewritten. Their upload
and false-negative confirmation remain evidence for the regression.

#### Starter tag-based release contract

The starter remains a vendored, tag-as-ship-decision product. A releasable tag:

1. matches the policy SemVer grammar;
2. was created through administrator-only release-tag authorization;
3. resolves to a commit reachable from the protected default branch;
4. has successful required CI for that exact SHA;
5. cannot be moved or deleted after creation.

Tag authorization and immutability are separate rulesets. A release-tag creation
ruleset may grant the administrator role a creation-only bypass. Branch
protection and the deletion/non-fast-forward tag ruleset have no bypass actors,
so the creation authority cannot move/delete tags or skip review/security gates.

Before any artifact reaches a privileged job, a read-only release-authorizer job
uses only the ephemeral repository-scoped `GITHUB_TOKEN` with explicit
`contents: read`, `actions: read`, and `checks: read` permissions (plus GitHub's
metadata read). It receives no repository secret, PAT, or administration token,
does not check out the tag, and must:

1. read immutable repository ID and current default branch;
2. resolve and peel the event tag to one commit and bind all downstream outputs
   to that SHA;
3. prove the event actor currently has administrator permission, failing closed
   on hidden/unknown actors or unreadable permission state;
4. prove the SHA is reachable from the fetched current protected default branch;
5. fetch the exact expected CI workflow/check runs for that SHA, require one
   unambiguous successful result from the trusted GitHub Actions app/workflow,
   and reject stale, duplicate-context, wrong-app, skipped, or missing results.

The authorizer emits a canonical evidence digest over repository ID, tag, SHA,
actor, default branch, and trusted workflow/check identity. Build manifests carry
that digest; privileged jobs verify it before promotion. Any unreadable API
response, changed repository/default branch, or failed precondition stops the
workflow.

Complete ruleset bypass state and CodeQL default-setup configuration are not read
inside the tag-triggered workflow. GitHub returns full `bypass_actors` only to a
caller with ruleset write access, and the CodeQL configuration endpoint requires
Administration read; placing either credential in a workflow definition selected
by an initially untrusted tag would recreate the privilege-exposure finding. The
starter installer and pre-release operator checkpoint instead use the operator's
local `gh` credentials to apply and fully read back those surfaces. No credential
is persisted. A required-reviewer `release` environment cannot be approved until
the current readback receipt is attached to the release checkpoint. If the
operator token, required scope, receipt, reviewer, exact CI check, or CodeQL
readiness is unavailable, the starter is non-ready and publication remains
blocked. This avoids both credential exposure and a fresh-repository ruleset
deadlock.

The starter default-branch ruleset uses the one-baseline posture:

- no bypass actors;
- PR required with the explicit solo-maintainer zero-approval exception;
- stale reviews dismissed and review threads resolved;
- strict required status checks;
- CodeQL high/critical enforcement;
- deletion and non-fast-forward protection;
- administrators subject to the protection.

The installer is dry-run by default, validates the slug, paginates, matches by
`(name, target)`, shows semantic changes, and requires
`--apply --confirm <plan-id>`.

Every starter publishing/deployment workflow follows the promotion invariant:

- build, test, and scan jobs have read-only/no-token permissions;
- they produce immutable artifacts plus canonical digest manifests;
- privileged jobs do not check out or execute consumer source;
- privileged jobs verify artifacts immediately before publishing;
- PyPI, GHCR, Pages, and GitHub Release mutation are isolated by required scope
  and protected environment where applicable.

Each target also has a byte-identity contract:

- **PyPI:** the distribution manifest above binds build, attestation, upload,
  PEP 691 digest readback, and clean exact-version installation.
- **GHCR:** each read-only build emits a canonical OCI archive/layout and digest;
  the scanner records the exact inspected digest and scan-result hash in the
  manifest. The publisher recomputes both, pushes without rebuilding, resolves
  remote per-architecture digests, creates the multi-architecture manifest only
  from those immutable digests, and verifies the remote index/alias digest.
- **Pages:** the read-only build records source SHA, docs-branch commit/tree,
  bundle hash, exact archived site-tree hash, and Pages artifact identity. The
  no-checkout push job verifies and fast-forwards that bundle; the deploy job
  consumes the same prebuilt site artifact, and branch/run/served-site evidence
  is read back without rebuilding.
- **GitHub Release:** release assets are the already-manifested artifacts. The
  final no-checkout job verifies the authorizer/tag target and asset digests,
  uploads once, then checks API-reported digests or downloads and rehashes when
  the platform omits them.

A manifest written beside an artifact is not scan evidence by itself. The
scanner input digest, publisher input digest, and remote output digest/tree must
form one verified chain. Structural and executable tests cover all four mutation
paths and forbid any rebuild after the gate.

### 9. Smaller but readiness-relevant corrections

- `.yamllint.yml` excludes `.worktrees/**`; the test runs the same
  `yamllint -s .` form as the strict gate against a synthetic nested worktree.
- Zizmor parsing returns gated findings and non-gating warnings separately.
  Every item is schema-validated. Unknown but well-formed audit IDs warn;
  malformed entries or an unknown top-level shape fail closed as corrupted tool
  output. Warnings reach `lint-actions`, `aviato validate`, strict validation, and
  CI logs without changing exit status; gated findings still fail every surface.
- The supply-chain specification is corrected to the accepted block-level,
  order/artifact-insensitive verifier. The frozen non-gating
  `dangerous-triggers`, mutable-shell `docker run` exclusion, and related
  accepted decisions are not silently reopened.
- `pyproject.toml` declares `README.md`; build verification inspects wheel and
  sdist metadata for description and content type.
- Living backlog/traceability/security records use current PR/release verbs and
  retain Dependabot, doctor, target proof, and other genuine blockers until
  evidence exists.
- Documentation tests assert semantic current-state facts rather than requiring
  stale token mentions.

### Canonical closure ownership

Before implementation claims an OR-ID complete, the living
`docs/requirements/traceability.md` gains an OR-to-requirement/control matrix
linking that ID to its canonical requirement/specification, implementation,
behavioral tests, and—where applicable—external evidence. Affected module
backlogs carry still-open OR work. This temporary design is never the sole owner
of completion state and is pruned only after every durable decision and link has
been promoted.

## Onboarding pilot and recovery runbook

Before the first real consumer onboarding, the operator records:

- repository slug, default branch, exact head, clean/dirty state, and declaration
  presence;
- existing branch/tag rulesets and classic/security/merge settings;
- environment protection and required checks;
- existing files at every desired/obsolete managed path;
- seed-sidecar and managed-inventory state.

The pilot proceeds through explicit checkpoints:

1. pinned read-only preview and transition-plan review;
2. local/temporary-clone execution and post-transition diagnosis;
3. reviewable proposal and CI/security verification;
4. protection-plan preview and confirmed apply;
5. remote readback plus `doctor` readiness;
6. abort/recovery exercise using only disposable state.

Abort criteria include a changed plan ID, source ref movement, untrusted path,
failed exact-SHA CI, unknown remote state, unexpected GitHub normalization, or
any partial mutation not represented in structured output. Recovery covers
rerunning idempotent file/protection plans, restoring captured settings when
explicitly authorized, and preserving evidence before cleanup. Restoration never
replays read-shaped API responses: it builds purpose-specific write payloads for
classic settings, security/merge toggles, environments, and named rulesets from
the captured semantic state, previews and confirms the restoration plan, and
requires full post-restore readback. Unknown/unsupported captured fields block
automatic restoration and remain manual evidence-backed recovery steps.

## Verification strategy

### TDD and focused evidence

Every production behavior change begins with a failing test that proves the
finding. Required test groups include:

- installed-versus-fetched registries across every consumer command;
- accessible-repository tag 404 versus hidden/private/auth-stale 404,
  auth/rate-limit/timeout/5xx/malformed resolution, annotated-tag peel failure,
  and ref movement before commit-SHA archive fetch;
- pipeline add/remove graph compilation, permissions, environments, checks,
  dependencies, and obsolete clean/dirty artifact retirement;
- fresh and existing-seed proposal sidecars plus post-merge idempotence;
- local/proposal collision matrices and no-mutation preflight;
- absent/partial/corrupt/adversarial managed inventories, marker-universe
  mismatch, obsolete workflow diagnosis, and transaction interruption at every
  operation boundary;
- canonical `.`, `/tmp`/`/private/tmp`, symlink, nested-directory, and non-repo
  targets;
- checkout-local bootstrap identity/preservation/rejection, unknown variable
  keys, and tri-state conditional partial previews;
- composite protection success, degradation, partial failure, and recovery;
- composite protection/ruleset plan stability, changed-plan refusal,
  repository-ID/default-branch/slug/pin mismatch, duplicate ruleset identities,
  safe owned deletion, full-detail fetch, per-write recheck, response-lost
  indeterminate results, post-write readback, and condition
  equivalence/indeterminate cases;
- doctor vectors for every readiness field and one all-green case;
- executable distribution-manifest and publisher-sidecar regressions;
- starter off-default-branch, non-admin, unreadable API, stale/missing/duplicate
  context/wrong-app CI refusal; privilege separation; CodeQL/readiness
  preflight; tag authorization/immutability; no-bypass branch posture; and
  target-specific PyPI/GHCR/Pages/Release byte-identity chains;
- warning-only and malformed-item zizmor behavior across parser/CLI/validate/CI,
  nested-worktree lint exclusion, semantic docs state, canonical OR traceability,
  purpose-built recovery/runbook structure, and package metadata.

Mocks may establish deterministic failure boundaries but must not assert only
that a mock was called. Integration tests use real temporary Git repositories,
real generated YAML/JSON, and executable workflow script bodies wherever
possible.

### Repository-wide gates

Before any external proof:

1. focused changed-area tests;
2. full test suite;
3. `aviato validate`;
4. `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh` from the repository root and
   from the isolated worktree topology;
5. clean wheel/sdist build, metadata inspection, and isolated wheel install;
6. generated-artifact and starter parity checks;
7. independent code review against every OR-ID in this document.

### External evidence

External proof is release-scoped and target-specific. Each row records exact
repository/commit/tag, workflow/job URLs, conclusions, ruleset/settings
readback, package/image/Pages/TestFlight identity where applicable, and cleanup
state. Failed or unknown proof retains its owning backlog item.

OR-022 is not closed by one generic consumer. The release-scoped matrix imports
the approved backlog-closure target set:

| Evidence row | Required proof |
|---|---|
| `python-library` | Exact onboarding/protection/doctor; real CI/security/release; TestPyPI trusted publication and install; the currently supported versioned Pages contract and served-tree identity; manifest/attestation identity and rollback/yank evidence. The separate design-doc inclusion/opt-out feature is not imported here. |
| `python-service` | Exact onboarding/protection/doctor; real CI/security/release; multi-architecture GHCR digests, scan binding, SBOM/provenance, monotonic alias, and rollback/delete evidence. |
| `node-service` | Exact onboarding/protection/doctor; real Node CI/security/release and GHCR profile proof. |
| `python-component` | Exact onboarding/protection/doctor; real zero-deployment release/security proof. |
| `swift-app` | Exact onboarding/protection/doctor; protected-environment build/upload proof and durable App Store Connect/TestFlight receipt, or an exact retained blocker with dependent aggregate rows still open. |

Every applicable Pages/GHCR/TestPyPI/Apple leaf backlog closes independently;
aggregate profile/deployment rows close only when all dependencies are proven.
Until the full matrix is evidenced, OR-022 and its owning canonical backlog rows
remain open and the overall “all findings fixed” goal is not complete, even if a
first disposable onboarding pilot is successful.

## External authority ledger

Repository implementation and tests require no external mutation authority.
The user's approval of this design authorizes local repository changes only. It
does **not** carry forward standing authority from another branch/design to
create or mutate any external repository, branch, pull request, issue, workflow,
environment, ruleset, package, site, or App Store object. Separate explicit
approval/checkpoints are required before:

- enabling or changing Dependabot/security settings on a live repository;
- creating disposable public proof repositories or changing any of their
  branches, PRs, issues, workflows, settings, environments, rulesets, or
  protection;
- merging protected remediation/release PRs;
- changing environment reviewers or other access controls;
- publishing to PyPI/TestPyPI/GHCR/Pages or uploading to TestFlight;
- yanking, deleting, retagging, rolling back, restoring, or cleaning up proof
  artifacts;
- deleting disposable repositories or hosted evidence.

## Acceptance criteria

The remediation is complete only when:

1. OR-001 through OR-021 each link to passing behavioral evidence and current
   implementation; OR-022 links to successful evidence for every applicable row
   in the full five-profile/target matrix, with any unavailable Apple row retained
   as an explicit blocker that prevents aggregate completion.
2. No consumer operation resolves templates/policy from an installed tree while
   recording another pin.
3. Removing a supported pipeline removes its executable and protection surface,
   and safe obsolete files disappear while untrusted files block.
4. Local and proposal onboarding produce the same converged state, including
   declaration, seed sidecar, managed inventory, and deletions.
5. Provision and `complete-protection` cover every protection surface and report
   partial/degraded state honestly.
6. A changed or uninspectable ruleset plan cannot be applied, and conditions can
   no longer disappear from a clean verdict.
7. `doctor` cannot return zero for any failed or unknown applicable signal.
8. Managed and starter publishing workflows satisfy the no-untrusted-computation
   in privileged jobs invariant.
9. The strict repository gate passes with sibling worktrees present, built
   package metadata is complete, and living documentation matches live evidence.
10. The onboarding pilot proves preview, proposal, protection, diagnosis,
    abort/recovery, and readback on disposable state before a production
    repository is enrolled.
