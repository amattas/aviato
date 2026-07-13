# PyPI deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [external verification] Publish the gated artifact to TestPyPI through the consumer-local trusted publisher and verify identity, provenance, and installability. — trace: §13.1


## Settled — do not reopen

- pip-audit stays `--strict`; no severity filter (R7-1: pip-audit JSON carries no severity).
