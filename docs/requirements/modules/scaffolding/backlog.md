# Scaffolding backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- (none)


## Settled — do not reopen

- Templates are only ever regenerated via `scripts/regen-templates.py`; never hand-edited. `aviato validate` fails on template/scaffold parity drift.
- Swift/Xcode project and package manifests remain operator-owned and are not seeded (§12.3); the earlier backlog request for a Swift manifest fragment contradicted that settled contract and is closed as a non-defect.
