# GHCR deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [external verification] Publish a disposable multi-architecture image and verify scanned-byte digest identity, SBOM/provenance, and monotonic aliases in GHCR. — trace: §13.2, SEC-005
- [external verification] The Trivy CLI pin jumped v0.55.0 → v0.72.0 (2026-07-16 dependency-matrix audit); a changelog scan of 0.56–0.72 found no SARIF/severity/exit-code breaking changes, but the scan gate + SARIF upload have not run live on the new version — confirm both on the first disposable-image run above. — source: 2026-07-16 dependency-matrix audit · .github/workflows/reusable-docker-ghcr.yml:186


## Settled — do not reopen

- GHCR stays single-job OIDC (R7-4, accepted documented scope with in-file rationale); only the byte-identity scan→push (promote the exact scanned OCI archives by digest, C12-W3) is in scope.
