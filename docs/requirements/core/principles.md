<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

## 2. Core Principles (non-negotiable)

These principles constrain every process and every module. A change that
violates one of these is wrong, regardless of how convenient it is.

### 2.1 Modularity (the central concept)

The system is a **composition of independent modules** around an
**agnostic core**. The core knows how to *resolve*, *compose*, *scaffold*,
*diagnose*, and *reconcile* — it knows nothing about any specific language or
deployment target.

- Every capability that is language-specific or deployment-specific lives in a
  **plug-in module**, never in the core.
- Adding a language, a documentation generator, a release mechanism, or a
  deployment target is done by **adding a module**, never by editing the core.
- Modules declare a typed interface (what they provide, what they require) and
  are composed — never hardcoded — by higher-level units.
- A profile is a **thin manifest that composes modules**; it contains no logic.

This is the single most important property of the architecture. See §4 for the
full model.

### 2.2 Zero downstream coupling

The Library has **no registry, no list, no record** of which repositories
consume it. It can be made public and forked freely. A Consumer self-declares
its relationship to the Library; the Library is inert with respect to Consumers.
(An operator may keep a *local, operator-side* list of repositories to scan —
§5.11 — but that list never lives in the Library.)

### 2.3 Privilege follows blast radius

Work is partitioned by how much damage it can do:

- **Low-privilege, automatable** work (reading state, opening pull requests,
  filing issues) runs unattended in Consumer automation.
- **High-privilege, mutating** work (changing protected settings) runs **only**
  when an authorized human initiates it, with their own credentials, after an
  explicit gate (§5.7/§5.8).
- **Deployment** is high-privilege and outward-facing but is authorized by a
  distinct, explicitly-defined mechanism (§2.12), not the §5.7 settings gate.

Automation may *propose*; mutation of a protected resource happens only through
an authorized path (§2.4, §2.12).

### 2.4 Report before mutate

Detected divergence is **reported** by automation and **applied** by a gated,
operator-initiated process (§5.7). Automation never silently changes a protected
*setting* to match a desired state. (Deployment publishes artifacts — a separate
action governed by §2.12 — and is not a settings mutation.)

### 2.5 Idempotency and managed-file safety

- Re-running any generative process on an unchanged input produces **no change**.
- Generated artifacts carry a **managed marker** (normative format: §6.2). The
  system refuses to overwrite a file that is **not** marked managed, and refuses
  to trust a file whose marker is malformed — unless the operator forces it.
- A file the operator hand-edited is never silently clobbered.
- Files that **cannot** carry an in-file marker (e.g. JSON without comments,
  legal text, lockfiles, binaries) and operator-owned source (build definitions,
  entrypoints) are handled by the **seed-once** rule (§6.3): scaffolded only when
  absent, never overwritten, and excluded from drift detection.

### 2.6 Version-pin compatibility

A Consumer pins the **version** of the Library it follows (an exact version or a
floating major reference). A process acting on a Consumer must honor that pin and
must **refuse** to act on a mismatch, unless explicitly overridden. The
**compatibility relation is defined**: the acting tool is *compatible* with a
Consumer's pin iff the acting tool's **major version equals the pinned major**
**and** the acting tool's version is **≥ the version recorded in that Consumer's
managed markers**. Anything else is incompatible → refuse (overridable only by an
explicit operator flag).

### 2.7 Fail-closed authorization

An authorization decision defaults to **deny**:

- A consent record must be re-validated against the **current** proposed change,
  not a stale one (§5.7, §5.8).
- A failed or ambiguous authorization lookup is treated as **not authorized**,
  never as authorized.
- Only a **real human actor** may grant consent. "Real human" is determined by
  the hosting platform's actor type on the authoritative event (actor type
  `User`, not `Bot`/`App`/service). If the actor type cannot be determined, the
  decision is **DENY**.

### 2.8 Apply-time recompute

A mutating apply never trusts a snapshot captured earlier. It **re-reads live
state at apply time**, recomputes the diff, and — if the recomputed diff differs
from what was proposed — **prompts the operator** before proceeding. If the
recomputed diff is **empty** (the change was already applied externally), it
**no-ops and records that on the tracking issue**, applying nothing. This
re-read covers **both** the live settings **and** the consent/issue channel
(§5.7): if the issue or its consent record changed since the granter was
identified, the apply aborts.

### 2.9 Clean boundaries with external systems

Data read from an external system (read-shaped) is **never replayed verbatim**
into a write to that system. Each write constructs a **purpose-built payload**
containing only the fields that write accepts.

### 2.10 Self-reference resolution (bootstrap)

The Library must be able to **consume its own conventions** and run its own
processes — **including its release pipeline** — **before** it has produced a
release. In the bootstrap state, every self-applied automation (scaffolding
**and** the release/verify pipelines) resolves its module/action references to
**self-contained local paths**, never to a not-yet-existing released reference.
The bootstrap state is detected by **structure**, not by name: a repository is
the Library iff it contains the Library's defining layout (its module-source
tree, profile/bundle definitions, and core package) — see §5.10 for the exact
predicate. Bootstrap is rejected anywhere that is not the Library (§5.4).

### 2.11 Safe provisioning order

When a process creates a new protected resource, it must **never** leave the
resource unprotected, and must **never** deadlock the resource's own first
operation by over-protecting it before that operation can occur. Provisioning is
**staged**: minimal protection that closes the exposure window first, full
protection after the first operation succeeds. The intermediate **partially
provisioned** state and its recovery are specified in §5.2.

### 2.12 Deployment authorization (the deployment gate)

Deployment is high-privilege and outward-facing, but it is **not** authorized by
the §5.7 settings gate. Its authorization model is:

- **The human gate is the release cut.** An operator merging the release
  proposal (§5.9) is the authorizing human action; the resulting version tag
  triggers deployment automatically.
- **Secret-bearing deploys add a second gate.** Any deploy that requires stored
  secrets (day zero: Apple App Store Connect) runs behind a **protected
  deployment environment with required reviewers** — a second human approval at
  deploy time.
- **Accepted risk:** there is a time-of-check/time-of-use window between the
  release cut and the tag-triggered deploy. This is accepted deliberately;
  deployment does **not** perform §2.8 apply-time recompute. This exemption is
  scoped to deployment alone and is stated here so it is a defined Part I
  principle, not a Part II improvisation. The exemption covers settings-state
  recompute only; it does **not** license a mutable published alias (e.g. a
  `latest` tag) to regress — concurrent tag-triggered deploys are ordered by a
  per-alias concurrency group and a monotonic-version guard (§13.2/§13.3, §8.14).

### 2.13 Security scanning is baseline

Security scanning is an **always-on baseline** of every profile — not a tier,
not opt-in. A repository cannot be Aviato-managed without it; there is no
composition that silently omits it. The baseline covers four categories:

- **SAST** (static analysis) per language;
- **Secret scanning with push protection**;
- **Dependency / supply-chain vulnerability scanning**;
- **Published-artifact security** (image vulnerability scan, SBOM, build
  provenance/attestation) for any profile that publishes an artifact.

**Gate policy:** **high/critical** findings **block**; **medium/low report** to the
platform's security surface without blocking; **secret-scanning push protection
always blocks**, regardless of severity. The gate is applied where each scan is
authoritative: **source scans (SAST, dependency) gate the verify pipeline on PRs
and are re-run on the release ref before any deploy** (so the deploy gate is
evaluated against the deployed code, not a stale PR head); **published-artifact
scans gate the publish itself** (§11.7). **Where each gate lives (GitHub binding):**
the **dependency** and **secret** scans gate **in-workflow** (the scanner's
exit-code fails the job on high/critical / any secret), and report **all severities**
as SARIF (medium/low surfaced, not blocked); **SAST (CodeQL)** is enforced twice after
the uploaded SARIF finishes processing: the workflow queries every page of open alerts
for the exact analyzed ref and CodeQL tool and fails on high/critical, while the branch
ruleset carries a CodeQL `code_scanning` rule with `alerts_threshold=none` and
`security_alerts_threshold=high_or_higher`. Doctor probes both code-scanning availability
and this exact merge-protection threshold. The required heartbeat remains an independent
freshness/availability signal and is uploaded only after all scan gates pass; it is not a
substitute for CodeQL severity enforcement.
**Enforcement is fail-closed:** a scan
whose required upload privilege is absent at runtime, or that cannot run, **fails
the pipeline** — it never passes silently (§5.14, §5.4, §8.16). **No external
service, no stored secret:** scans run on the platform token plus the
security-findings upload scope (the GitHub binding, §2.14: `security-events: write`
→ SARIF on the Security surface) — preserving §2.3 and §6.6. The concrete engines
are plug-in modules (§12/§13); the baseline-ness and the gate policy are core.

### 2.14 Hosting-platform binding (platform specifics live behind an interface)

The core is platform-agnostic, but it must name *some* concrete platform mechanics
to be implementable. Every such specific — the declaration file's path, permission
/ scope names, the security-findings format (SARIF) and its upload scope, the
commit convention that drives versioning, and the tag/ref mechanics of release and
floating-major advancement — is defined as a **hosting-platform binding
interface**, not as a core identifier. **GitHub is the sole day-zero binding;**
another platform would supply its own binding without changing core logic. Where
Part I states a GitHub literal — `.github/aviato.yaml` (§6.1); `security-events:
write` + SARIF (§2.13); Conventional Commits + the tag/floating-ref mechanics
(§5.9) — read it as "the GitHub binding's realization of an abstract capability."
The §9 falsifiable-agnosticism check targets the core *code* (no import edge into
the plug-in tree, no enumerated target identifier), not these binding values, and
is unaffected by them.

---
