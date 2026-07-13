# Versioning backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- (none)

## Resolved by 2026-07-12 hardening plan

- The release diagram states the monotonic major-alias guard, and generated callers bridge dispatch results into PR-visible required status contexts with policy-bound names and no bypass actors.

## Settled — do not reopen

- Release gate keeps `merge-base --is-ancestor` (R6-4); fixes may ADD SHA-binding, never re-tighten to tip equality.
- Tag-only release publishing; no stored release PAT; fail-closed `aviato-ref` (no `main` default).
- C12-W1 release privilege split (FINDINGS #2) is implemented: derive job runs `contents: read` with no token; only the propose/tag job holds `contents: write` + `pull-requests: write`; top-level `permissions: {}` (reusable-release.yml:71-200). The documented, accepted residual — the write job still installs the pinned Aviato with the write token ambient because a step cannot drop job permissions (defense-in-depth for the heavy derive phase, not elimination) — is recorded at reusable-release.yml:27-29 and SECURITY.md. Do not reopen.
