# Security backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [manual trust root] Configure real reviewer/team database IDs, apply the two-approval code-owner/last-push managed ruleset, and record two distinct non-author approvals for the exact privileged manifest candidate. Provisioning and protected apply remain intentionally blocked until this evidence exists. — trace: SEC-007
- [live verification] Use canary PR #59 to prove the applied ruleset blocks the critical CodeQL alert, then record the durable run/alert evidence and clean up the canary at the authorized checkpoint. — trace: SEC-010
- [live rollout] Enable Dependabot security updates and run `aviato doctor` now that ruleset convergence is verified. — trace: SEC-010


## Settled — do not reopen

- The former declaration-scoped `required_reviews: 0` exception is historical and has been superseded for Aviato's privileged trust root by the two-approval fail-closed policy. Generic consumer liveness policy remains documented separately. — trace: SEC-007
- §11.3 detector semantics are frozen: bashlex-AST taint, fail-closed, block-level verify. NO interpreter enumeration, any-word matching, order-aware verify, grep mirrors, or a second in-workflow checker (8d069f7, accf092, faaeb10, 66951ba, 9ccea23). The same impl runs in every consumer's CI via reusable-common-lint.yml — single implementation, no mirror to drift.
- zizmor scope decision (#18): the gate covers `unpinned-uses`, `unpinned-images`, and `template-injection`; `dangerous-triggers` stays non-gating (recorded in `zizmor.yml`, `docs/security/threat-model.md`, and §11.3).
- npm/Node hardening is only ever strengthened, never relaxed (S6).
