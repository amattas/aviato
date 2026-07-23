<!-- New document (2026-07-21). Direction, not authoritative requirements. -->

# Aviato Roadmap — from operator CLI to release bot

**Status:** Proposed roadmap / agreed design direction — **NOT authoritative.**
The single source of truth remains `docs/requirements/` (§ index in
`docs/requirements/README.md`). Where a phase below **changes** a core principle,
that change is a **proposal**: it is not in force until the owning requirement §
is amended and the validation gate updated. Nothing here relaxes a current §
principle by being written down.

**Current implementation status:** this roadmap and the provider-neutral
`Advisor` seam are the only landed bot work. There is not yet a running App,
webhook receiver, service, queue, dashboard, or service-backed flow. Aviato is a
bot only after the Phase-1 runtime and cutover exit gates below pass; adding a
port or publishing a container alone does not count.

This document records the target shape and the phased path for evolving Aviato
from an Operator-run CLI + reusable-workflow library into a service-backed
**release bot**, and — critically — which of Aviato's security principles are
**preserved**, which are **consciously renegotiated**, and what compensating
control replaces each one.

## Framing

Aviato today is not "cobbled-together scripts": it is an agnostic core engine
(`aviato/core/`) behind typed ports, plug-in data under `aviato/library/`,
§-numbered requirements/specifications, and a validation gate. What makes it
*feel* script-like is the **operating model**, not the code:

- it runs as a CLI from an Operator's workstation, under the Operator's own
  `gh` credentials (`aviato/github_platform.py` shells out to `gh api`);
- it has no identity of its own, no service, and no reaction to events;
- the only unattended surface is `reusable-consumer-automation.yml`, running on
  a schedule **inside each Consumer repo**.

"Becoming a bot" is therefore a **delivery/identity** change, not a rewrite. The
work adds split-purpose GitHub App identities, a webhook-driven Kubernetes
service, and service drivers/bindings around the agnostic core. New generic
orchestration may extend core ports and flows, but provider-, hosting-, and
deployment-specific logic stays outside core (§2.1/§4.3).

Three axes advance in parallel:

- **Autonomy** (the trust axis): report → autonomous releases → gated auto-apply
  → full autonomy. This is the axis that renegotiates §2 principles.
- **Track K** (platform): the Kubernetes service that hosts the flows.
- **Track L** (intelligence): LLM **advisors**, always advisory, never
  authoritative for a gating decision.

## Decisions (settled — do not reopen without revisiting this section)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Tenancy: internal-first, tenant-shaped.** One tenant now; every state row, config object, queue message, and credential lookup is keyed by `installation_id` from day one. | Multi-tenant later becomes a switch, not a migration. |
| D2 | **Identity: split-purpose GitHub Apps** (not Operator PATs), even single-tenant. The Bot App receives webhooks and reads/proposes; a separately registered Settings Executor App, introduced only in Phase 3, can mutate protected settings. No key can mint both proposal/content tokens and administration-write tokens. | Scoped, revocable, short-lived installation tokens preserve least privilege and actor-type distinction for §2.7; compromise of the public-facing webhook service does not automatically confer settings-admin privilege. |
| D3 | **LLM is advisory only, behind an `Advisor` port** (sibling to `Platform`); concrete binding outside core; provider name added to `aviato/plugins/denylist.txt` (§9b); `FakeAdvisor` for tests. Before the first advisor ships, the port gains typed provider-neutral unavailable and budget failures (a policy-denied variant existed while the binding targeted a policy-gated hosted endpoint; retired with the direct Anthropic binding, which has no producer for it). | The core stays deterministic and agnostic; model output never controls a required check, version, merge, tag, publish, deploy, or settings mutation. Typed failures permit a narrow fail-open path without catching unrelated programming errors. |
| D4 | **LLM egress: a contained commercial endpoint — the Anthropic API** (amended 2026-07-22; originally an Azure OpenAI-style private-link endpoint). Direct TLS to `api.anthropic.com` (no-train under commercial terms), model pinned to an immutable dated revision for cache/audit scoping; base URL stays per-installation config so a gateway or private routing can be interposed without code change. Cluster egress is bounded to TLS/443 by NetworkPolicy. | The model ingests diffs/commits/docs; a security-first tool must not open-egress Consumer code. The Advisor port stays provider-neutral, so the binding — not core — carries this decision. |
| D5 | **Platform: cloud-agnostic Kubernetes**, generic Postgres, native K8s Secrets, Postgres-as-queue, KEDA, Gateway API, and an independent retention-locked audit sink. | Mirrors the agnostic-core value; no cloud lock-in. Postgres is operational state, not the sole non-repudiation boundary. |
| D6 | **The cluster is the brain; GitHub Actions remains the hands for tagging, publishing, and deploying.** | The bot plans and proposes a release; after the human merges the release PR, the existing Consumer workflow creates the tag with its ephemeral `GITHUB_TOKEN` and runs the tag-pinned deploy. OIDC Trusted Publishing and deploy-environment gates stay bound to the Consumer workflow identity (§11.1/§11.2/§13.1). |
| D7 | **Phase-1 logic is service-centric:** the cluster reads state, computes drift, opens PRs/issues, and drafts release PRs; tag creation, publish, and deploy stay in Actions. | This is the "real bot" target, not a scheduler of scripts. |
| D8 | **Repo topology: a sibling `aviato-bot` repo now, converging to one repo later.** The bot is itself an Aviato-managed `python-service` Consumer. | Keeps the Library public/inert/forkable (§2.2) and its SemVer a clean Consumer contract (§2.6); maximal dogfood. |
| D9 | **Consolidation path: §10 Path A — lift the single-profile-per-repo restriction** (multi-profile-per-repo, each profile with its own declaration + independent pin). | Per-profile pins let services on older Library versions stay undisturbed through consolidation (§2.6 honored per profile). |
| D10 | **Gated-apply authorization: dashboard-native GitHub-OAuth from day one.** The approver authenticates as a GitHub `User`; the Operator CLI executes in Phases 1–2, and the isolated Settings Executor App executes from Phase 3. | A first-class control surface; §2.7 actor-type proof preserved by anchoring consent to a GitHub `User`, never an App. |
| D11 | **Webhook trust is fail-closed and delivery processing is idempotent.** Verify `X-Hub-Signature-256` over the unmodified request bytes before parsing; reject a missing/invalid signature; persist `X-GitHub-Delivery` plus the raw-body digest under a unique `(installation_id, delivery_id)` constraint before acknowledging. | GitHub retries and attackers can replay or forge HTTP requests. Authentication, durable acceptance, bounded replay detection, and de-duplication are prerequisites to every event-driven action. |
| D12 | **Credential posture changes when each capability appears, not at "full autonomy."** Phase 0 is read-only. Phase 1 introduces a stored proposal-capable Bot App key and amends §11.2/§14 before fleet enrollment. Phase 3 separately introduces the settings-write key. | A private key able to mint a write token is a write-capable stored credential even when each installation token is short-lived. The posture ledger must describe actual capability, not intended use. |

## Invariants (these do NOT change)

- **The core stays agnostic** (§2.1/§9b). Every new capability — App auth, the
  LLM, K8s — is a **binding or plug-in behind a port**. `aviato/core/*.py`
  never learns the words `kubernetes`, `azure`, `openai`, or any provider.
- **Publishing stays in the Consumer's Actions** (§11.1/§11.2/§13.1). The
  release-cut merge remains the human gate; the tag still triggers the in-repo
  deploy. The cluster orchestrates, decides, advises, proposes, and observes —
  it never becomes the publisher.
- **Tag creation also stays in the Consumer's Actions.** The Bot App never
  creates or moves a release tag. A model recommendation never enters the
  tagging input; the deterministic release workflow derives and verifies it.
- **The same `aviato.core` drives both the CLI and the service.** The CLI
  remains as the local / break-glass path; the service is an additional driver
  of the identical ports.
- **Report before mutate** (§2.4) holds unchanged through Phases 0–2. It is
  renegotiated only at Phase 3, and only for an explicitly signed low-risk tier.
- **The LLM never supplies an authoritative gate.** Deterministic
  `core.versioning` remains the source of truth for the version; the model may
  only draft prose or *raise a non-required flag* for a human. Model confidence
  cannot turn that flag into a failing required check (§2.5 idempotency
  preserved).

## Target architecture (Phase 1+)

### In-cluster — the brain

- **Gateway API → webhook/API receiver** (stateless, HPA-scaled): receives
  GitHub App webhooks (`push`, `pull_request`, `release`, `installation`) and
  serves the Operator dashboard/API. The webhook route retains the raw body,
  verifies `X-Hub-Signature-256` with a constant-time comparison before JSON
  parsing, allows a signed installation-lifecycle event to establish/remove
  installation state, rejects all other events for unknown
  installations/repositories, rejects a repeated delivery id or raw-body
  digest inside the replay window, and durably inserts the delivery before
  returning 2xx. Dashboard routes use a separate origin, session, and
  rate-limit policy.
- **Job workers** (KEDA-scaled on Postgres-queue depth): run the existing
  `aviato/core` flows — `file_drift_flow`, `settings_drift_flow`,
  `reconcile_flow`, `fleet` — plus release-PR drafting and LLM advisories. The
  bounded rate-limit retry already in `aviato/github.py` carries over. Every
  job has a deterministic key containing installation, repository, flow,
  declaration pin, input hash, and flow version; retries resume or no-op rather
  than open duplicate PRs/issues or repeat an advisory.
- **Postgres**: the state store (installations, per-profile pins, drift status,
  hash-chained audit log, LLM cache, accepted webhook deliveries) **and** the
  job queue (`FOR UPDATE SKIP LOCKED` / `pgmq`). Queue claim, retry, dead-letter,
  and lease-expiry behavior is specified and tested. A dedicated broker is a
  later upgrade, gated on volume, not a day-one dependency.
- **Independent audit sink**: periodically anchors the Postgres audit-chain
  head and stores signed consent/apply receipts under retention lock (for
  example, S3-compatible Object Lock/WORM or an enterprise append-only SIEM).
  The bot's database credentials cannot rewrite or delete those anchors.
- **Bindings**: a Bot-App-auth `Platform` implementation (mints
  per-installation, per-job permission-reduced tokens) alongside the existing
  `gh`-shelling `github_platform.py`; a separately deployed Settings Executor
  binding in Phase 3; and an installation-scoped `Advisor` binding for the
  contained LLM endpoint over a private link.
- **Explicit secret inventory**, separated by workload identity and RBAC:
  Bot App private key, GitHub webhook secret, GitHub OAuth client/session
  secrets, LLM endpoint credential, DB credentials, and audit-sink credential
  or signing material. The Phase-3 Settings Executor private key is held in a
  different Secret, service account, namespace policy, and deployment; webhook
  and general worker pods cannot read it.

### In GitHub — the hands

- Consumer Actions keep **verify / tag / release-gate / publish / deploy**
  (`reusable-release.yml`, `reusable-release-gate.yml`, and the deploy
  workflows) — OIDC, in-repo identity. The Bot App is the identity for every
  read, proposal, and issue the cluster performs.

### Shared

- `aviato.core` + its ports are the single engine. New bindings plug into the
  existing seam; the in-memory `tests/core/fakeplatform.py` (and a new
  `FakeAdvisor`) keep the flows unit-testable without live credentials.

### Consequence

The per-repo scheduled drift cron (`reusable-consumer-automation.yml`) largely
**retires for managed repos** once the cluster runs drift centrally; only the
verify/release/publish workflows remain in-repo (they must, for OIDC).

### Workflow-to-service ownership and cutover

| Capability | Before cutover | After Phase-1/2 cutover |
|------------|----------------|--------------------------|
| Scheduled file/settings drift | Consumer `aviato-drift.yml` caller | Service event + reconciliation jobs |
| Drift PRs and tracking issues | Consumer automation | Bot App |
| Release planning / release-PR drafting | Reusable release propose phase | Service release planner |
| Release tag creation | Consumer release workflow | **Consumer release workflow (unchanged trust boundary)** |
| Verify, required checks, security scans | Consumer Actions | Consumer Actions |
| Publish/deploy and protected environments | Consumer Actions | Consumer Actions |
| Break-glass audit/reconcile | Operator CLI | Operator CLI remains available |

Cutover is explicit per installation and profile; merely installing the App
does not disable Consumer automation. The service first runs in shadow mode,
records the result it *would* have emitted, and must agree with the existing
workflow for a defined observation window. The Operator then records a
cutover generation, the service becomes the sole drift proposer, and only then
does `sync` remove/disable the scheduled drift caller. A service health breach
halts new mutations and surfaces a runbook to re-enable the caller; dual
proposal writers are never left active.

## Phases

Phase **1 = A** (bot identity + proposal service, existing settings/deployment
authorization intact, credential posture explicitly amended); Phase **4 = B**
(full autonomy). Each phase ships value and de-risks the next.

### Phase 0 — Identity & client (no behavior change)

Register the Bot App with read-only production permissions. Add the App-auth
read path (per-installation token minting) beside `github_platform.py`, the
permission manifest, signature-verification library, delivery schema, and
secret-rotation runbook. Proposal payloads can be generated in dry-run; write
permissions are enabled only in an isolated test installation. Everything in
the fleet still runs as today; the CLI is unaffected. **No production
principle change.**

*Exit gate:* signed and forged webhook fixtures prove accept/reject behavior;
duplicate deliveries produce one durable job; the App reads a test
installation with parity to the `gh` path; production installation tokens
cannot write.

### Phase 1 — The service (proposal-capable) = A

Before enabling writes, amend §11.2/§14 to permit the narrowly scoped,
proposal-capable stored Bot App key and record its actual contents/issues/PR
capabilities. Stand up the full Kubernetes stack (§Track K) and the
service-centric flows (D7): central drift detection, file-drift PRs,
settings-drift tracking issues, and release-PR drafting — all
low-blast-radius but still write-capable. Persist installations, pins, accepted
deliveries, job state, drift status, and the audit chain. Ship the Operator
dashboard, including the
**dashboard-native gated-apply approval surface** (D10; §Gated-apply
authorization). Land the first two LLM advisors (release-notes draft; docs-update
verifier). Privileged settings mutation still flows through the operator-gated
§5.7 path: the dashboard records the diff-bound approval, but the Operator CLI
still recomputes and applies with the Operator's credentials.

*Proposed principle change:* **§2.2** — the App's installation list is a
permissioned inventory. It is inherent to an App, is not committed to the Library
repo, and does not make the Library non-inert toward Consumers (the Library still
holds no registry). Amend §2.2 to distinguish "the Library keeps no committed
Consumer registry" (unchanged) from "the service knows its own installations"
(new, permissioned).

*Proposed credential change:* **§11.2/§14** — unlike an ephemeral workflow
token, the stored Bot App private key can mint proposal/content-write tokens.
Contain it with per-job permission reduction, no ruleset bypass, release-gate
revalidation, namespace/RBAC isolation, rotation, anomaly alerts, and
break-glass installation suspension. It has no administration-write
permission.

*Proposed consent-surface change:* **§5.7/§6.4** — the authoritative grant
moves from a GitHub issue-label event to a dashboard-issued, diff-bound signed
receipt. The §2.7 human/role checks and §2.8 apply-time re-read remain
unchanged; the CLI verifies the receipt and external audit checkpoint before
applying. Issue labels/comments become notification and cross-reference
surfaces, not authorization.

*Exit gate:* one test installation completes signed webhook → durable job →
core flow → idempotent PR/issue → audit anchor end-to-end; replaying the same
delivery and job creates no duplicate or second LLM charge; the shadow window
matches Consumer automation; cutover is explicit; every protected-settings
change is still human-approved under the amended §5.7 fail-closed path.

### Phase 2 — Autonomous releases

The release-cut merge is already the human gate (§2.12/§11.1), so the bot owns
release **planning and proposal** without crossing §2.7: it computes the next
version (`core.versioning.next_version`, deterministic), writes the
version/changelog on a release branch, and opens or updates one release PR. The
only human action is the merge. The Consumer's existing release workflow then
creates the tag with its ephemeral `GITHUB_TOKEN` and runs the in-repo deploy;
the Bot App neither creates nor moves tags. The version-recommendation LLM
advisor lands here as a non-required *second opinion* over the deterministic
result.

*Principle change:* none — a `User` still merged.

*Exit gate:* duplicate/out-of-order merge and webhook deliveries converge on
one release PR and one version; the merged commit, tag, gate, artifact, and
deploy all identify the same SHA; the Bot App audit contains no tag-write call;
a human approves by merging.

### Phase 3 — Gated auto-apply of low-risk settings (start of B)

Introduce a **settings risk tier**. Low-blast-radius drift auto-reconciles inside
a *pre-authorized policy*; high-blast-radius drift (branch-protection relaxation,
required-reviews changes) always requires a live human approval. §2.8 apply-time
recompute and the §5.7 diff-binding carry over unchanged; high-risk applies
require **dual control** (two distinct `User`s). Register and deploy the
separate Settings Executor App only now; it has administration-write but no
contents, PR, issue, webhook, or OAuth role. The public receiver and general
workers submit a diff-bound command to the isolated executor and cannot mint
its token.

*Proposed principle changes:*

- **§2.4** (report before mutate) — automation may now *apply* a change, but only
  within a signed low-risk tier.
- **§2.7** — consent shifts from "a `User` grants consent per apply" to "a `User`
  pre-authorizes a *class* of remediations via signed policy." The human-in-the-
  loop moves from each-apply to policy-authoring; the policy is authored in the
  dashboard by an authenticated GitHub `User`.
- **§2.3** — "privilege follows blast radius" gains a **confidence/risk-tier**
  dimension.
- **§11.2/§14** — a second stored key can now mint administration-write tokens.
  This is the credential-posture change for protected settings; it occurs in
  Phase 3, not Phase 4.

*Exit gate:* low-risk drift self-heals under policy; high-risk still human-gated
and dual-controlled; compromise tests prove the Bot App cannot call settings
writes and the Settings Executor cannot push code, create tags, or approve its
own command.

### Phase 4 — Full autonomy = B

The bot applies settings/rulesets unattended within an expanded
pre-authorized policy envelope; humans handle exceptions and edit policy. This
is a different authorization model, adopted deliberately. It does not add a
new credential class: the isolated Settings Executor key arrived in Phase 3.

*Proposed principle change:* **§2.4/§2.7** — authorization moves from a live
human approval for high-risk changes to a signed policy envelope for every
covered class. Compensating controls: dual-controlled policy changes,
fine-grained per-installation scopes, retention-locked audit receipts,
break-glass installation suspension, anomaly detection, and §2.8 apply-time
recompute with diff bounds still enforced on every apply.

*Exit gate:* the envelope holds under audit; human involvement is exception-only.

### Phase overview

| Phase | Autonomy | Track K (platform) | Track L (LLM) | Proposed §-change |
|-------|----------|--------------------|---------------|-------------------|
| **0** | Read-only App identity + client parity | CLI still | — | none |
| **1 = A** | Service: central drift/proposals/release-PRs | Full K8s stack + dashboard | Release-notes draft; docs verifier | §2.2 + §5.7/§6.4 + §11.2/§14 (proposal key) |
| **2** | Autonomous releases (merge = gate) | — | Version recommendation | none |
| **3** | Gated auto-apply of low-risk settings | Isolated Settings Executor | advisories mature | §2.4 / §2.7 / §2.3 + §11.2/§14 (settings key) |
| **4 = B** | Full autonomy within policy envelope | — | — | §2.4 / §2.7 |

## Track L — LLM advisors

The `Advisor` port (D3) admits one contained binding day zero. Advisors are
ordered by blast radius, but every output remains non-authoritative regardless
of model confidence:

| Advisor | Role | Lands | Guardrail |
|---------|------|-------|-----------|
| **Release-notes draft** | Prose, reviewed at the release cut (§11.1) | P1–2 | Human edits before merge; safest first win |
| **Docs-update verifier** | PR comment: "you changed X, the docs still claim Y" | P1–2 | Always a non-required comment/check annotation; model confidence never makes it a gate |
| **Version recommendation** | Second opinion on the bump | P2–3 | Deterministic `core.versioning` stays the floor / source of truth; the model may only *raise a flag* (e.g. a breaking change mislabeled `fix:`), never lower or silently set the number |

The docs-update verifier is the **semantic** counterpart to Aviato's existing
**structural** drift checks (policy-pattern drift, template-scaffold parity,
monotonic-alias parity in `aviato/validation.py`): those catch a diverged copy;
the advisor catches prose that no longer matches behavior.

Guardrails, in force for every advisor:

- **Determinism** — deterministic decoding (temperature 0) reduces variation
  but is not treated as a reproducibility guarantee. The service-side
  advisory coordinator (outside the agnostic core) caches on
  `(installation-id, endpoint-id, immutable-model-revision, feature,
  prompt-version, policy-version, input-hash)` so tenants and endpoint policies
  cannot share entries and identical accepted input never re-bills. Failures
  are not cached as successful advice (§2.5).
- **Auditability** — every call's prompt, response, model, and prompt-version is
  persisted under its installation and anchored in the external audit sink;
  the exact cached response is reviewable. Re-executing a hosted model is not
  mislabeled as bit-for-bit reproducibility.
- **Fail-open-but-loud** — model unavailable or over budget ⇒ skip the advisory,
  emit a loud warning + audit entry, and **never block** a release or PR.
  Advisory work runs as a separate job from deterministic proposal/gate work.
  Its caller catches only the port's typed expected failures; an unexpected
  exception fails that advisory job loudly and is never converted into
  success-shaped advice.
- **Egress** — a contained endpoint over a private link; the surface the model
  sees is diffs + commit messages + docs, not the whole repo; the endpoint is
  per-installation config so a future tenant can bring its own.

## Track K — Kubernetes (cloud-agnostic)

- **Portable primitives only** — Deployments/Services/**Gateway API** (no
  cloud-LB annotations), **HPA + KEDA** (CNCF). No cloud workload-identity
  (IRSA/Entra/GCP-WI).
- **Postgres is just a `DATABASE_URL`** — in-cluster (e.g. CloudNativePG) or any
  external instance; the app does not care.
- **Queue = Postgres-as-queue** (`FOR UPDATE SKIP LOCKED` / `pgmq`); KEDA has a
  Postgres scaler. A dedicated broker (Redis/NATS) is a later, volume-gated
  upgrade.
- **Secrets = native K8s Secrets with an explicit inventory** (App private
  keys, webhook secret, OAuth/session secrets, LLM key, DB credentials, and
  audit material), isolated by workload rather than mounted into one service.
- **Delivery** — Helm/Kustomize + GitOps (Argo/Flux), consistent with Aviato's
  policy-as-code posture. The bot's own container image is built and released by
  the §13.2 GHCR pipeline (Trivy + SBOM + provenance) it manages for others.
- **Observability** — OTel/Prometheus; Aviato's "loud failure" convention maps
  to real alerts.

### Honest posture note — native K8s Secrets

Native Secrets are base64 in etcd, not a vault. For a security-first tool
holding App private keys and endpoint credentials, the compensating controls
are: **etcd encryption-at-rest**, **RBAC-scoped per-workload Secret access**,
**SOPS/sealed-secrets** so nothing sits plaintext in Git, short key rotation,
and network-policy isolation. GitHub App *tokens* are short-lived; the private
keys remain long-lived write-capability roots and are treated accordingly.
Webhook-secret rotation accepts old+new only for a bounded overlap and records
which key verified each delivery.

## Repo topology & consolidation

The service lives in a **sibling `aviato-bot` repo** that depends on a pinned,
published `aviato`. During early port churn (P0–P1), development uses a local
editable path dependency (`pip install -e ../aviato`) so iteration is instant
while the *declared* dependency stays a real pinned version. `aviato-bot` is
itself an Aviato-managed `python-service` Consumer: it carries its own
`.github/aviato.yml`, pins the Library, gets scaffolded workflows, and ships its
image through the §13.2 pipeline. This keeps the Library repo lean, public,
inert, and forkable (§2.2), and its SemVer a clean Consumer contract (§2.6).

**Design for convergence** — the eventual merge to one repo must be a move, not a
rewrite:

- the dev path dependency **is** the future monorepo workspace dependency;
- the service touches only `aviato.core`'s **public port surface**, never private
  internals, so "imported from a wheel" vs "from a sibling package" is a pure
  packaging detail;
- `aviato-bot/` is a self-contained package (`src/aviato_bot/`, `deploy/`,
  `tests/`, own `pyproject.toml`) that drops into `packages/aviato-bot/`
  unchanged;
- **independent, tag-prefixed version streams** (`aviato-vX` / `aviato-bot-vY`)
  from day one.

**Consolidation requires §10 Path A (D9).** Aviato's day-zero scope explicitly
lists "library-and-service-in-one-repo," "multi-package," and "single profile per
repository" as non-goals (§10). Converging to one repo means lifting that
restriction: **multi-profile-per-repo, each profile with its own declaration and
independent pin.** This is a genuine core workstream — it touches the
single-profile assumptions in the declaration (§6.1), composition (§5.1),
managed-marker/scaffold scoping (now path-scoped so Library and service files
cannot collide, §6.2/§5.3), and drift/onboard/sync/repin/offboard — and it is a
**prerequisite to the merge**. Per-profile pins are what let a service on an older
Library pin remain undisturbed through consolidation.

## Gated-apply authorization (§5.7 in the service)

The service acts through Apps, but §2.7 requires consent from a real human,
actor type `User` — never `Bot`/`App` — fail-closed. The rule: **an App may be
the hands, never the authority.** A gated apply is *authorized* by a human and
executed by the Operator CLI in Phases 1–2 or by the isolated Settings Executor
from Phase 3 — the same brain/hands split as publishing (D6), applied to
consent.

Two layers, kept separate:

- **Access** — who may open the dashboard → corporate SSO/OIDC is acceptable.
- **Consent authority** — who may *sign* an apply → must resolve to a GitHub
  `User`, so §2.7's actor-type proof survives. SSO gates the door; a GitHub-User
  identity signs the approval. Letting SSO *be* the consent authority would
  silently redefine "real human" (§2.7/§2.14) and is out of scope.

Per D10, the consent surface is **dashboard-native from day one** (GitHub OAuth),
with these day-one requirements to stay §2.7-faithful and fail-closed:

- **Actor type** — a GitHub OAuth user-access token identifies a `User` (not the
  App's installation token); record the `login`/`id`. Identity unresolved ⇒
  **DENY**. The user token is short-lived, is not retained after approval, and
  is never used to perform the mutation.
- **Authorization** — after login, verify the user's repo/org role (admin/maintain
  or a designated approver team) *via the App*. Role lookup failed/ambiguous ⇒
  **DENY**.
- **Diff-binding** — approval is for an exact `diff-id`; at apply, re-read live
  state and recompute (§2.8); a differing diff aborts/re-prompts, an empty diff
  no-ops and records. A live-approval receipt is short-lived, nonce-bound, and
  consumed transactionally once, so an old approval cannot authorize a later
  A→B→A recurrence of the same diff.
- **Step-up on approve** — the approve action requires a fresh explicit auth
  gesture, plus CSRF tokens, `SameSite` cookies, and short sessions, so a
  long-lived dashboard session cannot silently consent.
- **Audit as consent system-of-record** — record installation, repository,
  profile, approver id, role, `diff-id`, timestamp, policy version, and the
  recomputed-diff hash in an **append-only / hash-chained** log; write a signed
  authorization receipt and chain-head checkpoint to the independent
  retention-locked sink before execution, then anchor the outcome receipt.
  Sink unavailable or the pre-execution checkpoint failed ⇒ **DENY**.

**Core is already shaped for this.** The consent model in `aviato/core/ports.py`
already carries the neutral fields — `consent_actor_type`, `consent_role` +
`consent_role_lookup_ok`, `consent_diff_id`, `ambiguous`,
`edited_by_nonhuman_since_grant`. This requires a port-surface refactor, not a
change to the authorization decision: generalize the type name `Issue` → a
surface-neutral `ConsentRecord` (the fields are already neutral) to keep the
§9b agnostic discipline.

**Tradeoff — recover external non-repudiation.** Dashboard-native consent gives
up GitHub's external issue timeline as the authoritative record. The
retention-locked audit receipt above is the non-repudiation control. Mirror its
receipt id + digest back to a repo issue comment for Operator visibility and
cross-reference only; GitHub comments are editable/deletable and are explicitly
**not** treated as immutable evidence or authorization.

**`Approval ≠ auto-apply`.** Every gated apply still needs a live human approval;
Phase 3's pre-authorized low-risk tiers are *also signed here*, later.

## Consolidated posture ledger

| Concern | Tension with | Phase | Containment |
|---------|--------------|-------|-------------|
| Installation inventory | §2.2 | 1 | Permissioned App list, not committed to the Library repo |
| Auto-apply of settings | §2.4 | 3 | Only within a signed low-risk tier |
| Consent | §2.7 | 3 | Pre-authorized **policy** consent, signed by a GitHub `User` |
| Privilege model | §2.3 | 3 | Blast radius **+ confidence/risk-tier** |
| Stored proposal/content-write credential (Bot App key) | §11.2 / §14 | 1 | Permission-reduced short-lived tokens; no administration write or bypass; isolated Secret; release gate; break-glass suspend |
| Stored protected-settings credential (Settings Executor key) | §11.2 / §14 | 3 | Separate App/deployment/RBAC; no contents/PR/webhook access; diff-bound commands; dual control; break-glass suspend |
| LLM egress (diffs/docs) | security-first | 1 | Contained endpoint, private link, per-installation policy |
| LLM nondeterminism | §2.5 | 1 | Advisory-only; temperature 0; cached; audited |
| Static creds in K8s Secrets | vault-ideal | 1 | etcd encryption + per-workload RBAC + SOPS + rotation + network policy |
| Webhook forgery/replay | §2.7 / §2.5 | 0–1 | Raw-body HMAC verification; durable delivery id; unique constraint; idempotent jobs |
| Dashboard consent evidence | §2.7 / §2.8 | 1 | Diff-bound signed receipt; external retention-locked anchor; issue comment is visibility only |

Phase 0 leaves the production threat model intact. Phase 1 deliberately adds a
proposal-capable stored credential; Phase 3 adds a separately isolated
settings-write credential and pre-authorized low-risk applies; Phase 4 expands
the authorization envelope. Each change lands only after its requirement,
threat-model, control, and validation updates.

## Conversion definition of done

The conversion is complete only when all of the following are persistent and
operator-verifiable:

1. The `aviato-bot` service repository contains the receiver, API/dashboard,
   workers, Postgres migrations, App and Advisor bindings, deploy manifests,
   permission manifests, runbooks, and tests; production does not depend on an
   editable sibling checkout.
2. Signed webhook acceptance, forged-request rejection, duplicate delivery,
   queue retry/lease expiry, out-of-order events, token expiry, rate limiting,
   model outage/budget exhaustion, DB restart, and audit-sink outage have
   explicit behavior and automated tests.
3. One real test installation proves event → durable job → pinned
   `aviato.core` flow → idempotent PR/issue/release proposal → Consumer
   tag/publish workflow → anchored audit evidence without stored publish
   credentials.
4. App permission manifests are machine-checked against observed API calls.
   The Bot App cannot write protected settings; the Settings Executor cannot
   push content, create tags, receive webhooks, or authorize itself; neither
   App is a ruleset bypass actor.
5. Per-installation enrollment, suspension, key rotation, uninstallation,
   deletion/retention, backup/restore, and disaster-recovery paths are
   documented and exercised. Uninstallation revokes queued work and tokens
   before any further action.
6. Workflow cutover completes the shadow/equality window, records a generation,
   leaves one proposal writer, and preserves the Operator CLI as a tested
   break-glass path. Remaining Consumer workflows are intentionally retained
   according to the ownership table above.
7. The authoritative requirements, specifications, threat model, controls, and
   traceability matrix describe the service-backed behavior and carry evidence;
   this roadmap is not used as a substitute for those updates.

## Open items (not yet decided)

- **Dashboard access SSO provider** (distinct from consent authority, which is
  fixed to GitHub `User`).
- **Broker-upgrade threshold** — the fleet size / queue-depth at which
  Postgres-as-queue is replaced by a dedicated broker.
- **Prompt-version governance** — how prompt templates are versioned, reviewed,
  and pinned (they participate in the LLM cache key and audit record).
- **Risk-tier catalog** (Phase 3) — the exact settings classified low- vs
  high-blast-radius, and the signed-policy schema.
- **Multi-profile declaration format** (§10 Path A) — one declaration listing
  profiles vs per-path declarations, and how managed markers are path-scoped.

## Related documents

- Requirements (authoritative outcomes/constraints): `requirements/README.md`.
- Specifications (testable behavior): `specifications/README.md`.
- Architecture (current implementation map): `architecture/overview.md`.
- Security (threats/controls): `security/threat-model.md`,
  `security/controls.md`.
