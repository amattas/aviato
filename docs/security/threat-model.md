# Aviato threat model

This living model covers the operator CLI, reusable workflows, scaffolded
consumer files, ruleset mutations, and release/deployment paths. Public
vulnerability reporting remains in [`SECURITY.md`](../../SECURITY.md). Control
details live in [`controls.md`](controls.md); status and evidence live in the
[`traceability matrix`](../requirements/traceability.md).

## Assets and actors

- **Assets:** consumer source, release artifacts, package/container identities,
  signing material, platform tokens, repository settings, security findings,
  release tags, and published documentation.
- **Actors:** consumer contributors, repository operators, GitHub Actions,
  external registries, GitHub Apps/actions, and attackers controlling a fork,
  dependency, template input, or compromised contributor account.
- **Assumption:** one trusted operator initiates protected settings mutations;
  unattended automation may read state and propose changes but not apply them.

## Trust boundaries

1. Local operator workstation ↔ GitHub API through the authenticated `gh` CLI.
2. Library-controlled reusable workflow ↔ consumer-controlled repository code.
3. Pull-request/fork context ↔ privileged base-repository workflow context.
4. Build/scan jobs ↔ publish/deploy jobs and external registries.
5. Declarative policy/templates ↔ generated files and shell/workflow execution.

## THREAT-001 — Consumer code reaches privileged credentials

Custom build, test, version, or submit commands may be attacker-controlled.
Running them while publishing, signing, or settings credentials are ambient can
exfiltrate or misuse those credentials. **Mitigations:** SEC-001, SEC-002.
**Residual risk:** GHCR's accepted single-job OIDC scope remains bounded by
byte-identity promotion and in-file rationale.

## THREAT-002 — Untrusted pull requests enter privileged workflow context

`workflow_run`, fork pull requests, or mutable refs can cause base-repository
workflows to check out and execute untrusted code with elevated permissions.
**Mitigations:** SEC-002, SEC-003. **Residual risk:** platform event semantics
remain an external dependency and require live canary verification.

## THREAT-003 — Mutable or injected supply-chain input executes

Unpinned actions/images/tools, `curl | shell`, plain `npx`, workflow template
injection, or install scripts can introduce code not represented by the reviewed
commit. **Mitigation:** SEC-004. **Residual risk:** selected non-gating zizmor
audits remain reported rather than blocked.

## THREAT-004 — Release or security evidence binds to the wrong commit

A moving branch/tag, stale pull-request result, or inconsistent checkout can
make a gate analyze one commit while publishing another. **Mitigations:**
SEC-003, SEC-005.

## THREAT-005 — Published bytes differ from scanned bytes

Rebuilding after an artifact scan can publish content that never passed the
security gate. **Mitigation:** SEC-005. **Residual risk:** third-party registry
availability and post-publication behavior remain external.

## THREAT-006 — Authorization or protection failure degrades open

Ambiguous API failures, stale consent, retained ruleset bypasses, or unsupported
rule handling can silently weaken protected settings. **Mitigations:** SEC-006,
SEC-007. **Residual risks:** GitHub may not support tag metadata-pattern rules;
that one proven case is reported as degraded while immutability remains. A
documented solo-maintainer exception may set the required-review count to zero
only while no independent eligible reviewer exists. That accepted absence of
independent human review retains PR, machine-gate, immutability, and no-bypass
protections and ends when another eligible reviewer is granted access.

## THREAT-007 — Secrets persist, leak to logs, or enter declarations

Credentials can be written into generated configuration, persisted by checkout,
materialized before approval, or retained after use. **Mitigations:** SEC-001,
SEC-008. **Residual risk:** the declaration guard is type/name-based and does
not content-inspect ordinary string variables.

## THREAT-008 — Generated paths or variables escape their intended boundary

Malicious or malformed names, symlinks, template variables, or repository slugs
can redirect reads/writes or inject workflow content. **Mitigations:** SEC-004,
SEC-009.

## THREAT-009 — Vulnerable code or dependency reaches a protected branch/release

Missing, stale, or bypassed SAST/dependency/secret evidence can allow known
high-impact findings into a release. **Mitigation:** SEC-010. **Residual risk:**
scanner/provider outages block authoritative gates and may require operator
recovery rather than automated downgrade.

## THREAT-010 — Documentation deployment receives unnecessary privilege

Building documentation from consumer code in the same job that can push or
deploy Pages exposes write/OIDC permissions. **Mitigations:** SEC-002, SEC-005.
The Aviato repository does not publish a self-site; consumer docs deployment
remains an opt-in capability.
