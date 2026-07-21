# Aviato requirements — § index

**Status:** Authoritative requirements (single source of truth).

This document has two parts:

- **Part I — Core (§1–§9):** language- and deployment-**agnostic**. It defines
  *what* the system must do, the *processes* it runs, and the *modular
  structure* it must have. The core contains no language- or
  deployment-specific logic; such capabilities are supplied as **plug-in
  modules** that conform to the interfaces defined here.
- **Part II — Day-Zero Plug-in Catalog (§10–§17):** the **concrete** set of
  language and deployment plug-ins required at day zero (Python, Node, Swift;
  PyPI, GHCR, GitHub Pages docs, Apple App Store Connect), each expressed purely
  as a composition of the generic module kinds from Part I. The core never
  changes to accommodate them.

§18 is the glossary. Part II realizes Part I; where Part II needs an
authorization or gating mechanism, that mechanism is defined as a Part I
principle first (§2) and merely *applied* in Part II.

**Day-zero scope boundaries (deliberate non-goals):** a single profile per
repository (no monorepo / multi-package / library-and-service-in-one-repo); a
single operator (no team/concurrent-operator/handoff model); a single
strictness level (no `standard`/`hardened` tier split). Each is called out where
relevant and may be revisited post-day-zero.

---

# Part I — Core (agnostic)

> Split from the monolithic REQUIREMENTS.md on 2026-07-11. § numbering is preserved
> verbatim in the split files, so code citations like §5.2 remain valid. Start with
> `core/` for outcomes and constraints. Precise behavioral contracts live under
> `../specifications/`. Open backlog work is tracked as [GitHub issues labeled
> `backlog`](https://github.com/amattas/aviato/issues?q=is%3Aissue+label%3Abacklog);
> settled "do not reopen" decisions live in a "Settled decisions — do not reopen"
> section on each owning module's page.

## § → file index

| § | Section | File |
|---|---|---|
| §1 | Purpose | core/purpose.md |
| §2 | Core Principles (non-negotiable) | core/principles.md |
| §2.1 | Modularity (the central concept) | core/principles.md |
| §2.2 | Zero downstream coupling | core/principles.md |
| §2.3 | Privilege follows blast radius | core/principles.md |
| §2.4 | Report before mutate | core/principles.md |
| §2.5 | Idempotency and managed-file safety | core/principles.md |
| §2.6 | Version-pin compatibility | core/principles.md |
| §2.7 | Fail-closed authorization | core/principles.md |
| §2.8 | Apply-time recompute | core/principles.md |
| §2.9 | Clean boundaries with external systems | core/principles.md |
| §2.10 | Self-reference resolution (bootstrap) | core/principles.md |
| §2.11 | Safe provisioning order | core/principles.md |
| §2.12 | Deployment authorization (the deployment gate) | core/principles.md |
| §2.13 | Security scanning is baseline | core/principles.md |
| §2.14 | Hosting-platform binding (platform specifics live behind an interface) | core/principles.md |
| §3 | System Structure | core/structure.md |
| §3.1 | The three actors and the boundary between them | core/structure.md |
| §3.2 | Module taxonomy | core/structure.md |
| §3.3 | Structural rules | core/structure.md |
| §3.4 | Single-operator scope (day-zero non-goal) | core/structure.md |
| §4 | The Modularity Model | core/modularity.md |
| §4.1 | Composition: a profile is an assembly of modules | core/modularity.md |
| §4.2 | Inheritance and override semantics (explicit, never silent) | core/modularity.md |
| §4.3 | Adding a capability = adding a module | core/modularity.md |
| §5 | Process Flows | core/modularity.md |
| §5.1 | Profile resolution & composition (pure) | core/modularity.md |
| §5.2 | Repository onboarding (provision-new and adopt-existing) | ../specifications/modules/onboarding/flow.md |
| §5.3 | Scaffolding / sync | ../specifications/modules/scaffolding/sync.md |
| §5.4 | Diagnosis (doctor) | ../specifications/modules/fleet/diagnosis.md |
| §5.5 | File drift detection (automated, propose-only) | ../specifications/modules/drift/file-drift.md |
| §5.6 | Settings drift detection (automated, report-only) | ../specifications/modules/drift/settings-drift.md |
| §5.7 | Settings reconciliation (operator-gated apply) | ../specifications/modules/reconcile/flow.md |
| §5.8 | Authorization gate (reused by §5.7 and any settings mutation) | ../specifications/modules/reconcile/consent.md |
| §5.9 | Library versioning & release | ../specifications/modules/versioning/release.md |
| §5.10 | Bootstrap / self-reference resolution | ../specifications/modules/onboarding/bootstrap.md |
| §5.11 | Local fleet scan | ../specifications/modules/fleet/scan.md |
| §5.12 | Version upgrade / downgrade (re-pin) | ../specifications/modules/versioning/repin.md |
| §5.13 | Offboarding (leave Aviato) | ../specifications/modules/offboarding/flow.md |
| §5.14 | Security scanning (baseline) | ../specifications/modules/security/scanning.md |
| §6 | The Consumer Contract | ../specifications/core/consumer-contract.md |
| §6.1 | Declaration file | ../specifications/core/consumer-contract.md |
| §6.2 | Managed-marker format (normative) | ../specifications/core/consumer-contract.md |
| §6.3 | Non-annotatable & operator-owned files (seed-once) | ../specifications/core/consumer-contract.md |
| §6.4 | Consent record (normative) | ../specifications/core/consumer-contract.md |
| §6.5 | Profile name stability | ../specifications/core/consumer-contract.md |
| §6.6 | Variable schema | ../specifications/core/consumer-contract.md |
| §7 | State & Sources of Truth | core/state-and-failures.md |
| §8 | Failure Modes the Structure Must Prevent | core/state-and-failures.md |
| §9 | Definition of Done (process-level, agnostic) | core/definition-of-done.md |
| §9b | Core-level Definition of Done (falsifiable agnosticism) | core/definition-of-done.md |
| §10 | Day-Zero Scope | modules/README.md |
| §10.1 | Languages and deployment targets | modules/README.md |
| §10.2 | Language → target mapping | modules/languages/README.md |
| §10.3 | Composition (one profile per repo, no tiers) | modules/README.md |
| §11 | Cross-Cutting Deployment Requirements | modules/deployment/README.md |
| §11.1 | The release is the human gate | modules/deployment/README.md |
| §11.2 | Credential posture: OIDC-first, stored secrets only where unavoidable | modules/deployment/README.md |
| §11.3 | Privileges are declared and granted (read and deploy alike) | ../specifications/modules/security/supply-chain.md |
| §11.4 | Stored-secret confinement (App Store Connect) | ../specifications/modules/deployment/apple/requirements.md |
| §11.5 | Runner requirements | modules/deployment/README.md |
| §11.6 | Definition of done for a deployment plug-in | modules/deployment/README.md |
| §11.7 | Published-artifact security gate | modules/deployment/README.md |
| §12 | Language Plug-ins | modules/languages/README.md |
| §12.1 | Python | ../specifications/modules/languages/python/requirements.md |
| §12.2 | Node (TypeScript + JavaScript) | ../specifications/modules/languages/node/requirements.md |
| §12.3 | Swift | ../specifications/modules/languages/swift/requirements.md |
| §13 | Deployment Plug-ins | modules/deployment/README.md |
| §13.1 | PyPI (OIDC Trusted Publishing) | ../specifications/modules/deployment/pypi/requirements.md |
| §13.2 | GHCR (GitHub Container Registry) | ../specifications/modules/deployment/ghcr/requirements.md |
| §13.3 | Documentation site (Zensical → docs branch, multi-version) | ../specifications/modules/deployment/docs-site/requirements.md |
| §13.4 | Apple App Store Connect | ../specifications/modules/deployment/apple/requirements.md |
| §13.5 | Rollback / yank (manual, day-zero) | modules/deployment/README.md |
| §14 | Secret & Credential Model (summary matrix) | modules/deployment/README.md |
| §15 | Profile Composition Matrix (day-zero) | modules/README.md |
| §16 | Per-Plug-in Definition of Done | modules/README.md |
| §17 | Operator Prerequisite Checklist (out-of-band setup) | modules/README.md |
| §18 | Glossary | core/glossary.md |
