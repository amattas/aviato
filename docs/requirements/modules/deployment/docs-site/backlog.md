# Docs-site deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [low] The docs-caller↔CI-caller display-name parity check (`_check_docs_caller_name_parity`) scans only scaffold template files, not rendered instances — the managed `.github/workflows/aviato-docs.yml` and consumer rendered workflows aren't checked for the `workflow_run` name coupling, so a rename there silently kills docs deploys. Extend the check to rendered instances. — FINDINGS #40 (narrowed) · aviato/validation.py:240-255
- [low] Replace the mike bridge with Zensical-native versioning when it ships — mike fork pinned at 2d4ad79 meanwhile. — spec 2026-07-11

## Settled — do not reopen

- Algolia docs search stays and is configurable (cdbaaeb) — opt-in `algolia` profile variable, default off; do not flip back to local search.
- Docs for ALL releases are kept — no pruning by default; `docs-retention` is an optional cap, default unlimited (#37, operator decision 2026-06-09).
- Zensical everywhere — supersedes "Docusaurus everywhere" (G1) and "Algolia stays, configurable" (operator decision 2026-07-11); search is Zensical built-in.
