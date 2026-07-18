# GHCR deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [external verification] Multi-platform SARIF category fix (per-arch `runs[0].automationDetails.id` stamp, PR #90, released in 0.4.2) has not yet run a real amd64+arm64 release — the first multi-arch consumer publish (container-fleet migration, G2) is its live verification. The underlying collision (all arch uploads shared the auto category) is fixed; only the live proof remains. — source: 2026-07-18 §13.2 live proof · .github/workflows/reusable-docker-ghcr.yml


## Settled — do not reopen

- GHCR stays single-job OIDC (R7-4, accepted documented scope with in-file rationale); only the byte-identity scan→push (promote the exact scanned OCI archives by digest, C12-W3) is in scope.
- §13.2 disposable-image proof PROVEN 2026-07-18 (single-arch): byte-identical scanned digest pushed on 3 independent releases, Trivy v0.72 SARIF + HIGH/CRITICAL gate clean, SBOM artifact present, provenance attestation verifies (`gh attestation verify` exit 0), release-tag manifest references only the scanned digest, and the monotonic `latest` alias correctly moved for a minor release and correctly stayed for a hand-tagged old-line patch. The 2026-07-16 Trivy v0.55→v0.72 pin bump surfaced a real regression (buildx `type=oci` tarball unreadable by Trivy 0.72's changed local-artifact detection) — fixed in aviato PR #85 (extract to an unpacked OCI layout dir before scanning). See [traceability §13.2](../../../traceability.md) and the [2026-07-18 evidence record](../../../evidence/2026-07-18-deploy-proofs.md).
