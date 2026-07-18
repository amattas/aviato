# GHCR deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [external verification] Multi-platform releases collide on the code-scanning SARIF category (both arch uploads use the auto category .github/workflows/aviato-ci.yml:docker), so only single-arch publishes complete; fix requires a per-platform category on the Trivy SARIF upload in reusable-docker-ghcr.yml. Blocks the container-fleet migration phase (G2 requires arm64). — source: 2026-07-18 §13.2 live proof


## Settled — do not reopen

- GHCR stays single-job OIDC (R7-4, accepted documented scope with in-file rationale); only the byte-identity scan→push (promote the exact scanned OCI archives by digest, C12-W3) is in scope.
- §13.2 disposable-image proof PROVEN 2026-07-18 (single-arch): byte-identical scanned digest pushed on 3 independent releases, Trivy v0.72 SARIF + HIGH/CRITICAL gate clean, SBOM artifact present, provenance attestation verifies (`gh attestation verify` exit 0), release-tag manifest references only the scanned digest, and the monotonic `latest` alias correctly moved for a minor release and correctly stayed for a hand-tagged old-line patch. The 2026-07-16 Trivy v0.55→v0.72 pin bump surfaced a real regression (buildx `type=oci` tarball unreadable by Trivy 0.72's changed local-artifact detection) — fixed in aviato PR #85 (extract to an unpacked OCI layout dir before scanning). See [traceability §13.2](../../../traceability.md) and the [2026-07-18 evidence record](../../../evidence/2026-07-18-deploy-proofs.md).
