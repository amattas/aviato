# Deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

Per-target backlogs live under `pypi/`, `ghcr/`, `docs-site/`, and `apple/`.

## Open

- (none)

## Settled — do not reopen

- §11.6/§13.5/SEC-005 rollback/yank proof PROVEN 2026-07-18 — all four deployment legs executed or documented: GHCR registry rollback demonstrated live (deleted the bad-release manifest/arch/attestation versions on amattas/aviato-proof-ghcr's package; registry rolled back to the prior good releases, `latest` removed alongside the bad manifest); floating-major tag hand-de-advanced from the bad release's commit back to the prior good commit; PyPI leg proven via the §13.1 TestPyPI yank (pending operator UI click); docs-site leg is git-revertable by design (documented mechanism, no live demo needed — reverting the `gh-pages` branch is a plain git revert). See [traceability §11.6, §13.5, SEC-005](../../traceability.md) and the [2026-07-18 evidence record](../../evidence/2026-07-18-deploy-proofs.md).
