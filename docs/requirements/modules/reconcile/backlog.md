# Reconcile backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [process] complete-protection/apply-rulesets do not reconcile a pre-existing classic branch-protection required-review count that outranks the declared ruleset override (the live proofs needed a manual classic-protection PATCH); teach the §5.7 apply path to reconcile classic protection or fail loudly. — source: 2026-07-18 live proofs

## Settled — do not reopen

- Single-operator consent TOCTOU is ACCEPTED (153fdfa) — the diff-bound `--confirm` gate is deliberately scoped to a single trusted operator; not re-filed.
