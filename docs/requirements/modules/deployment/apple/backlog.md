# Apple deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [med] The App Store environment reviewer gate (reusable-app-store-connect.yml:176) only checks that a `required_reviewers` rule EXISTS, not that its reviewers list is non-empty — an environment with an empty reviewers list passes the check but provides no protection. Match the Python check (`len(reviewers) > 0`). — FINDINGS #5 (narrowed) · .github/workflows/reusable-app-store-connect.yml:176; cf. aviato/github.py:228-232
- [low] The App Store upload receipt is still a retention-limited (90-day) artifact; `if-no-files-found` now errors, but §13.4.7 wants the receipt in release notes/declaration for durable availability. — FINDINGS #34 · .github/workflows/reusable-app-store-connect.yml:474

## Settled — do not reopen

- (none)
