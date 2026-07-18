# PyPI deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- (none)


## Settled — do not reopen

- pip-audit stays `--strict`; no severity filter (R7-1: pip-audit JSON carries no severity).
- §13.1 TestPyPI proof PROVEN 2026-07-17: aviato 0.4.1a2 published via the consumer-local OIDC trusted publisher (environment `pypi`, required reviewer), PEP 691 confirmation green, pip-download from the test index verified, `gh attestation verify` exit 0. Real-PyPI half already satisfied by production releases 0.3.0/0.4.0/0.4.1. TestPyPI yank of 0.4.1a2 is a pending operator UI click (§11.6 hygiene), not a code gap. See [traceability §13.1](../../../traceability.md) and the [2026-07-18 evidence record](../../../evidence/2026-07-18-deploy-proofs.md).
