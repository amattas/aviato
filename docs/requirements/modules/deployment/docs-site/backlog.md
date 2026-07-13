# Docs-site deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [external watch] Replace the pinned mike bridge with Zensical-native versioning when that capability ships; until then `aviato/library/docs-toolchain.yaml` owns the immutable fork SHA and the sync script updates every generated copy. — spec 2026-07-11

## Resolved by 2026-07-12 hardening plan

- Docs caller-name parity includes authoritative, generated, and rendered instances; missing sources fail closed.
- Docs callers dropped the inert artifact permission, and one policy file plus `sync-docs-toolchain-pins.py` owns all exact tool pins.

## Settled — do not reopen

- Docs for ALL releases are kept — no pruning by default; `docs-retention` is an optional cap, default unlimited (#37, operator decision 2026-06-09).
- Zensical with built-in search is the only current docs baseline (operator decision 2026-07-11); prior Docusaurus and Algolia decisions are historical and superseded.
