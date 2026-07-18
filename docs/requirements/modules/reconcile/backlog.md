# Reconcile backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

_None._

## Settled — do not reopen

- Single-operator consent TOCTOU is ACCEPTED (153fdfa) — the diff-bound `--confirm` gate is deliberately scoped to a single trusted operator; not re-filed.
