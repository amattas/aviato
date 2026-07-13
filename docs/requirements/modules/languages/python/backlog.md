# Python language backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- (none)

## Resolved by 2026-07-12 hardening plan

- The Python component profile exposes and forwards the same optional `typecheck-command` contract as the library profile.

## Settled — do not reopen

- (none)
- Numeric coverage remains opt-in and measure-only unless a consumer chooses a threshold; Aviato does not invent one universal percentage for heterogeneous repositories.
