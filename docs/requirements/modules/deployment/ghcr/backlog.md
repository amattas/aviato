# GHCR deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [low] §6.3/§13.2 (and a "seed-once prerequisite" line) still describe Dockerfile seeding despite the R5-6 decision that Dockerfiles are probe-only, never seeded. Amend the requirements text. — FINDINGS #56 · docs/requirements/core/consumer-contract.md (§6.3) + docs/requirements/modules/deployment/ghcr/requirements.md (§13.2)

## Settled — do not reopen

- GHCR stays single-job OIDC (R7-4, accepted documented scope with in-file rationale); only the byte-identity scan→push (promote the exact scanned OCI archives by digest, C12-W3) is in scope.
