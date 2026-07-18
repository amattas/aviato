# Docs-site deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [external watch] Replace the pinned mike bridge with Zensical-native versioning when that capability ships; until then `aviato/library/docs-toolchain.yaml` owns the immutable fork SHA and the sync script updates every generated copy. — spec 2026-07-11


## Settled — do not reopen

- Docs for ALL releases are kept — no pruning by default; `docs-retention` is an optional cap, default unlimited (#37, operator decision 2026-06-09).
- Zensical with built-in search is the only current docs baseline (operator decision 2026-07-11); prior Docusaurus and Algolia decisions are historical and superseded.
- §13.3 disposable-consumer Pages proof PROVEN 2026-07-17: branch DoD (version dir + `latest` symlink alias), served-site DoD (root/`latest`/versioned URLs 200, sitemap, search index, Mermaid rendering), and the §8.14 monotonic-alias DoD (minor release moves `latest`; old-line hand-tagged patch does not) all verified live on a disposable public repo, after fixing a real upstream bug (`reusable-docs-pages.yml` ran `git archive` under the docs working-directory instead of the repo root, silently producing an empty Pages artifact — fixed in aviato PR #85). See [traceability §13.3](../../../traceability.md) and the [2026-07-18 evidence record](../../../evidence/2026-07-18-deploy-proofs.md).
