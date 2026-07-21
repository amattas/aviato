<!-- New document (2026-07-21). Direction, not authoritative requirements. -->

# Aviato Roadmap — from operator CLI to release bot

**Status:** Proposed roadmap / agreed design direction — **NOT authoritative.**
The single source of truth remains `docs/requirements/` (§ index in
`docs/requirements/README.md`). Where a phase below **changes** a core principle,
that change is a **proposal**: it is not in force until the owning requirement §
is amended and the validation gate updated. Nothing here relaxes a current §
principle by being written down.

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
work adds an identity (a GitHub App), a service (webhook-driven, in Kubernetes),
and two new **bindings behind existing ports** — never new logic in the agnostic
core (§2.1/§4.3).

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
| D2 | **Identity: a GitHub App** (not an Operator PAT), even single-tenant. | Scoped, revocable, short-lived installation tokens, and actor-type-distinguishable for the §2.7 gate. |
| D3 | **LLM is advisory only, behind an `Advisor` port** (sibling to `Platform`); concrete binding outside core; provider name added to `aviato/plugins/denylist.txt` (§9b); `FakeAdvisor` for tests. | The core stays deterministic and agnostic; the model never picks a value that gates a publish. |
| D4 | **LLM egress: a contained hosted endpoint** (Azure OpenAI-style: no-train, in-tenant/region), reached over a private link; endpoint is per-installation config. | The model ingests diffs/commits/docs; a security-first tool must not open-egress Consumer code. |
| D5 | **Platform: cloud-agnostic Kubernetes**, generic Postgres, native K8s Secrets, Postgres-as-queue, KEDA, Gateway API. | Mirrors the agnostic-core value; no cloud lock-in. |
| D6 | **The cluster is the brain; GitHub Actions remains the hands for publishing.** | OIDC Trusted Publishing and the deploy-environment gates bind to the Consumer repo's workflow identity (§11.1/§11.2/§13.1); publishing from the cluster would reintroduce stored publish credentials. |
| D7 | **Phase-1 logic is service-centric:** the cluster reads state, computes drift, opens PRs/issues, and drafts release PRs; only publish/deploy stays in Actions. | This is the "real bot" target, not a scheduler of scripts. |
| D8 | **Repo topology: a sibling `aviato-bot` repo now, converging to one repo later.** The bot is itself an Aviato-managed `python-service` Consumer. | Keeps the Library public/inert/forkable (§2.2) and its SemVer a clean Consumer contract (§2.6); maximal dogfood. |
| D9 | **Consolidation path: §10 Path A — lift the single-profile-per-repo restriction** (multi-profile-per-repo, each profile with its own declaration + independent pin). | Per-profile pins let services on older Library versions stay undisturbed through consolidation (§2.6 honored per profile). |
| D10 | **Gated-apply authorization: dashboard-native GitHub-OAuth from day one.** The approver authenticates as a GitHub `User`; the App executes. | A first-class control surface; §2.7 actor-type proof preserved by anchoring consent to a GitHub `User`, not the App. |

## Invariants (these do NOT change)

- **The core stays agnostic** (§2.1/§9b). Every new capability — App auth, the
  LLM, K8s — is a **binding or plug-in behind a port**. `aviato/core/*.py`
  never learns the words `kubernetes`, `azure`, `openai`, or any provider.
- **Publishing stays in the Consumer's Actions** (§11.1/§11.2/§13.1). The
  release-cut merge remains the human gate; the tag still triggers the in-repo
  deploy. The cluster orchestrates, decides, advises, proposes, and observes —
  it never becomes the publisher.
- **The same `aviato.core` drives both the CLI and the service.** The CLI
  remains as the local / break-glass path; the service is an additional driver
  of the identical ports.
- **Report before mutate** (§2.4) holds unchanged through Phases 0–2. It is
  renegotiated only at Phase 3, and only for an explicitly signed low-risk tier.
- **The LLM never gates a publish.** Deterministic `core.versioning` remains the
  source of truth for the version; the model may only draft prose or *raise a
  flag* for a human (§2.5 idempotency preserved).

## Target architecture (Phase 1+)

### In-cluster — the brain

- **Gateway API → webhook/API receiver** (stateless, HPA-scaled): receives
  GitHub App webhooks (`push`, `pull_request`, `release`, `installation`) and
  serves the Operator dashboard/API.
- **Job workers** (KEDA-scaled on Postgres-queue depth): run the existing
  `aviato/core` flows — `file_drift_flow`, `settings_drift_flow`,
  `reconcile_flow`, `fleet` — plus release-PR drafting and LLM advisories. The
  bounded rate-limit retry already in `aviato/github.py` carries over.
- **Postgres**: the state store (installations, per-profile pins, drift status,
  audit log, LLM cache) **and** the job queue (`FOR UPDATE SKIP LOCKED` /
  `pgmq`). A dedicated broker is a later upgrade, gated on volume, not a day-one
  dependency.
- **Bindings**: an App-auth `Platform` implementation (mints per-installation
  tokens from the App private key) alongside the existing `gh`-shelling
  `github_platform.py`; an `Advisor` implementation for the contained LLM
  endpoint over a private link.
- **K8s Secrets** holding exactly three things: the **GitHub App private key**,
  the **LLM key**, and **DB credentials**.

### In GitHub — the hands

- Consumer Actions keep **verify / release-gate / publish / deploy**
  (`reusable-release.yml`, `reusable-release-gate.yml`, and the deploy
  workflows) — OIDC, in-repo identity. The App is the identity for every read,
  proposal, and issue the cluster performs.

### Shared

- `aviato.core` + its ports are the single engine. New bindings plug into the
  existing seam; the in-memory `tests/core/fakeplatform.py` (and a new
  `FakeAdvisor`) keep the flows unit-testable without live credentials.

### Consequence

The per-repo scheduled drift cron (`reusable-consumer-automation.yml`) largely
**retires for managed repos** once the cluster runs drift centrally; only the
verify/release/publish workflows remain in-repo (they must, for OIDC).

## Phases

Phase **1 = A** (bot identity + service, safety model intact); Phase **4 = B**
(full autonomy). Each phase ships value and de-risks the next.

### Phase 0 — Identity & client (no behavior change)

Register the GitHub App. Add the App-auth `Platform` binding (per-installation
token minting) beside `github_platform.py`. Everything still runs as today; the
CLI is unaffected. **No principle change.**

*Exit gate:* the App reads/proposes on a test installation with parity to the
`gh` path.

### Phase 1 — The service (report-only) = A

Stand up the full Kubernetes stack (§Track K) and the service-centric flows
(D7): central drift detection, file-drift PRs, settings-drift tracking issues,
and release-PR drafting — all low-privilege. Persist installations, pins, drift
status, and the audit log. Ship the Operator dashboard, including the
**dashboard-native gated-apply approval surface** (D10; §Gated-apply
authorization). Land the first two LLM advisors (release-notes draft; docs-update
verifier). Privileged settings mutation still flows through the operator-gated
§5.7 path — now surfaced in the dashboard rather than the CLI.

*Proposed principle change:* **§2.2** — the App's installation list is a
permissioned inventory. It is inherent to an App, is not committed to the Library
repo, and does not make the Library non-inert toward Consumers (the Library still
holds no registry). Amend §2.2 to distinguish "the Library keeps no committed
Consumer registry" (unchanged) from "the service knows its own installations"
(new, permissioned).

*Exit gate:* the fleet is watched end-to-end; every privileged change is still
human-approved.

### Phase 2 — Autonomous releases

The release-cut merge is already the human gate (§2.12/§11.1), so the bot can own
the release **mechanics** without crossing §2.7: on the qualifying merge signal it
computes the next version (`core.versioning.next_version`, deterministic), cuts
the tag, and lets the in-repo deploy run. Optionally it auto-opens the release PR
from Conventional Commits so the only human action is the merge. The
version-recommendation LLM advisor lands here as a *second opinion* over the
deterministic floor.

*Principle change:* none — a `User` still merged.

*Exit gate:* hands-off releases; a human approves by merging.

### Phase 3 — Gated auto-apply of low-risk settings (start of B)

Introduce a **settings risk tier**. Low-blast-radius drift auto-reconciles inside
a *pre-authorized policy*; high-blast-radius drift (branch-protection relaxation,
required-reviews changes) always requires a live human approval. §2.8 apply-time
recompute and the §5.7 diff-binding carry over unchanged; high-risk applies
require **dual control** (two distinct `User`s).

*Proposed principle changes:*

- **§2.4** (report before mutate) — automation may now *apply* a change, but only
  within a signed low-risk tier.
- **§2.7** — consent shifts from "a `User` grants consent per apply" to "a `User`
  pre-authorizes a *class* of remediations via signed policy." The human-in-the-
  loop moves from each-apply to policy-authoring; the policy is authored in the
  dashboard by an authenticated GitHub `User`.
- **§2.3** — "privilege follows blast radius" gains a **confidence/risk-tier**
  dimension.

*Exit gate:* low-risk drift self-heals under policy; high-risk still human-gated
and dual-controlled.

### Phase 4 — Full autonomy = B

The bot applies settings/rulesets unattended within the pre-authorized policy
envelope; humans handle exceptions and edit policy. This is a different threat
model, adopted deliberately.

*Proposed principle change:* **§11.2/§14** — the App now holds continuously
write-capable credentials (today the posture is "no write-capable stored
secret"). Compensating controls: fine-grained per-installation scopes, a
tamper-evident audit log, break-glass revocation, anomaly detection, and §2.8
apply-time recompute with diff bounds still enforced on every apply.

*Exit gate:* the envelope holds under audit; human involvement is exception-only.

### Phase overview

| Phase | Autonomy | Track K (platform) | Track L (LLM) | Proposed §-change |
|-------|----------|--------------------|---------------|-------------------|
| **0** | App identity + client parity | CLI still | — | none |
| **1 = A** | Service: central drift/proposals/release-PRs, report-only | Full K8s stack + dashboard | Release-notes draft; docs verifier | §2.2 |
| **2** | Autonomous releases (merge = gate) | — | Version recommendation | none |
| **3** | Gated auto-apply of low-risk settings | — | advisories mature | §2.4 / §2.7 / §2.3 |
| **4 = B** | Full autonomy within policy envelope | — | — | §11.2 / §14 |

## Track L — LLM advisors

The `Advisor` port (D3) admits one contained binding day zero. Advisors are
ordered by blast radius and mirror the §2.13 gate policy (high-confidence acts,
low reports):

| Advisor | Role | Lands | Guardrail |
|---------|------|-------|-----------|
| **Release-notes draft** | Prose, reviewed at the release cut (§11.1) | P1–2 | Human edits before merge; safest first win |
| **Docs-update verifier** | PR comment: "you changed X, the docs still claim Y" | P1–2 | Advisory; hard-fail only on high confidence, else comment |
| **Version recommendation** | Second opinion on the bump | P2–3 | Deterministic `core.versioning` stays the floor / source of truth; the model may only *raise a flag* (e.g. a breaking change mislabeled `fix:`), never lower or silently set the number |

The docs-update verifier is the **semantic** counterpart to Aviato's existing
**structural** drift checks (policy-pattern drift, template-scaffold parity,
monotonic-alias parity in `aviato/validation.py`): those catch a diverged copy;
the advisor catches prose that no longer matches behavior.

Guardrails, in force for every advisor:

- **Determinism** — deterministic decoding (temperature 0); cache keyed on
  `(feature, model, prompt-version, input-hash)` so identical input never
  re-bills or re-varies (§2.5).
- **Auditability** — every call's prompt, response, model, and prompt-version is
  persisted to the audit log; runs are reproducible and reviewable.
- **Fail-open-but-loud** — model unavailable or over budget ⇒ skip the advisory,
  emit a loud warning + audit entry, and **never block** a release or PR.
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
- **Secrets = native K8s Secrets** (App private key, LLM key, DB creds).
- **Delivery** — Helm/Kustomize + GitOps (Argo/Flux), consistent with Aviato's
  policy-as-code posture. The bot's own container image is built and released by
  the §13.2 GHCR pipeline (Trivy + SBOM + provenance) it manages for others.
- **Observability** — OTel/Prometheus; Aviato's "loud failure" convention maps
  to real alerts.

### Honest posture note — native K8s Secrets

Native Secrets are base64 in etcd, not a vault. For a security-first tool holding
the App private key + LLM key, the compensating controls are: **etcd
encryption-at-rest**, **RBAC-scoped** Secret access, **SOPS/sealed-secrets** so
nothing sits plaintext in Git, and short key rotation. GitHub App *tokens* are
already short-lived; only the private key is long-lived. This is a deliberate
step down from cloud workload-identity, contained by those four controls.

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

The service is an App, but §2.7 requires consent from a real human, actor type
`User` — never `Bot`/`App` — fail-closed. The rule: **the App is the hands, never
the authority.** A gated apply is *authorized* by a human and only *executed* by
the App — the same brain/hands split as publishing (D6), applied to consent.

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
  **DENY**.
- **Authorization** — after login, verify the user's repo/org role (admin/maintain
  or a designated approver team) *via the App*. Role lookup failed/ambiguous ⇒
  **DENY**.
- **Diff-binding** — approval is for an exact `diff-id`; at apply, re-read live
  state and recompute (§2.8); a differing diff aborts/re-prompts, an empty diff
  no-ops and records.
- **Step-up on approve** — the approve action requires a fresh explicit auth
  gesture, plus CSRF tokens, `SameSite` cookies, and short sessions, so a
  long-lived dashboard session cannot silently consent.
- **Audit as consent system-of-record** — record approver id, role, `diff-id`,
  timestamp, and the recomputed-diff hash in an **append-only / hash-chained**
  log.

**Core is already shaped for this.** The consent model in `aviato/core/ports.py`
already carries the neutral fields — `consent_actor_type`, `consent_role` +
`consent_role_lookup_ok`, `consent_diff_id`, `ambiguous`,
`edited_by_nonhuman_since_grant`. This is a **binding change, not a core-model
change**; the one refactor is to generalize the port type name `Issue` → a
surface-neutral `ConsentRecord` (the fields are already neutral) to keep the §9b
agnostic discipline.

**Tradeoff — recover external non-repudiation.** Dashboard-native consent gives up
GitHub's external, tamper-evident issue timeline as the record. Compensate by
**mirroring each approval back to a repo issue comment**: the dashboard is the UX;
the mirrored comment restores an external, immutable record.

**`Approval ≠ auto-apply`.** Every gated apply still needs a live human approval;
Phase 3's pre-authorized low-risk tiers are *also signed here*, later.

## Consolidated posture ledger

| Concern | Tension with | Phase | Containment |
|---------|--------------|-------|-------------|
| Installation inventory | §2.2 | 1 | Permissioned App list, not committed to the Library repo |
| Auto-apply of settings | §2.4 | 3 | Only within a signed low-risk tier |
| Consent | §2.7 | 3 | Pre-authorized **policy** consent, signed by a GitHub `User` |
| Privilege model | §2.3 | 3 | Blast radius **+ confidence/risk-tier** |
| Stored write-capable creds (App key) | §11.2 / §14 | 4 | Short-lived tokens; only the private key long-lived; break-glass revoke; fine-grained scopes |
| LLM egress (diffs/docs) | security-first | 1 | Contained endpoint, private link, per-installation policy |
| LLM nondeterminism | §2.5 | 1 | Advisory-only; temperature 0; cached; audited |
| Static creds in K8s Secrets | vault-ideal | 1 | etcd encryption + RBAC + SOPS + rotation |

Phases 0–2 leave the threat model intact; 3–4 renegotiate it deliberately, one
control at a time.

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
