# Onboarding backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [process] Fresh repos have the GitHub Actions "can create and approve pull requests" permission OFF, which breaks the release automation's release-PR creation on every new consumer (worked around by operator-opened release PRs in both live proofs); model the toggle in provisioning/settings (PUT /repos/{owner}/{repo}/actions/permissions/workflow) or document it as an onboarding prerequisite. — source: 2026-07-18 live proofs


## Settled — do not reopen

- (none)
