# Onboarding backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- (none)

## Resolved by 2026-07-12 hardening plan

- Provisioning and ruleset application use canonical slug validation before any GitHub call.
- Ruleset apply retries only a proven unsupported tag metadata rule, preserves tag immutability, and reports degraded posture.

## Settled — do not reopen

- (none)
