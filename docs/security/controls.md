# Aviato security controls

This inventory maps stable security control IDs to threats, implementation, and
verification surfaces. The [`threat model`](threat-model.md) owns risk analysis;
the [`security architecture`](../architecture/security.md) owns placement; the
[`traceability matrix`](../requirements/traceability.md) owns current state.

## SEC-001 — Confine credentials to minimal steps and environments

Addresses THREAT-001 and THREAT-007. Secret-bearing deploys require protected
environments; custom consumer commands run before secrets materialize or after
cleanup. See `reusable-asc-deploy.yml`, `reusable-pypi-publish.yml`, and the
consumer-local PyPI publisher contract. Verification: workflow guard tests and
operator verification of required reviewers.

## SEC-002 — Separate untrusted computation from privileged mutation

Addresses THREAT-001, THREAT-002, and THREAT-010. Read/build/scan jobs hand
immutable outputs to narrowly privileged publish, Pages, or settings paths.
Top-level workflow permissions are empty or read-only; privileged jobs declare
only their required permissions. Verification: pipeline-privilege and workflow
guard tests.

## SEC-003 — Bind every gate to one immutable commit

Addresses THREAT-002 and THREAT-004. Checkout, release gating, CodeQL analysis,
SARIF upload, heartbeat, tag verification, and PR status bridging resolve one
target SHA. Verification: release/security workflow tests and live release-head
dispatch evidence.

## SEC-004 — Pin and lint executable supply-chain inputs

Addresses THREAT-003 and THREAT-008. Third-party actions/images use digests;
registry tools use exact pins; zizmor plus shell-AST and `npx` checks block the
adopted unsafe patterns. Verification: action-pin, workflow, and negative
validation tests.

## SEC-005 — Promote verified artifacts without rebuilding

Addresses THREAT-004, THREAT-005, and THREAT-010. Deploy paths transfer the
exact gated artifact/archive/tree between low- and high-privilege jobs and
verify digest/SHA identity immediately before publication. Verification:
workflow guard tests; external registry/Pages proof remains operator-run.

## SEC-006 — Fail closed on mutation authorization

Addresses THREAT-006. Settings apply re-reads live state and consent, binds
confirmation to the current diff, rejects ambiguous actors/responses, and uses
purpose-built write payloads. Verification: consent, reconciliation, GitHub
binding, and CLI tests.

## SEC-007 — Enforce branch/tag protection without bypass

Addresses THREAT-006 and THREAT-009. The target posture requires PR/check/CodeQL
gates, blocks branch/tag deletion and non-fast-forward changes, and explicitly
clears bypass actors. Only a correlated unsupported tag pattern may degrade,
while immutability stays enforced. The corrective no-bypass payload is approved
in PR #60, but its merge and live reapply remain outstanding; this control is
therefore blocked rather than implemented.

## SEC-008 — Prevent secret persistence

Addresses THREAT-007. Secret-typed variables cannot enter declarations or
rendered artifacts; non-pushing checkouts disable persisted credentials; signing
assets are cleaned before post-submit commands. Verification: variable,
workflow, and validation-negative tests.

## SEC-009 — Confine paths, slugs, and rendered variables

Addresses THREAT-008. Repository slugs are canonicalized before GitHub calls;
generated targets are confined against traversal/symlink escapes; variable
schemas reject undeclared or secret misuse. Verification: pathguard, generator,
variable, and command-hardening tests.

## SEC-010 — Gate source and release security evidence

Addresses THREAT-009. SAST, dependency, secret, and artifact scanning are
baseline capabilities. High/critical findings block; CodeQL is queried for the
exact ref and reinforced by a ruleset threshold; heartbeat is independent
freshness evidence. Verification: security-baseline tests, CodeQL canary, and
live alert inspection.
