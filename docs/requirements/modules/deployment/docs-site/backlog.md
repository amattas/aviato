# Docs-site deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [external watch] Replace the pinned mike bridge with Zensical-native versioning when that capability ships; until then `aviato/library/docs-toolchain.yaml` owns the immutable fork SHA and the sync script updates every generated copy. — spec 2026-07-11
- [process] Every default-branch push should rebuild the `dev` docs version (operator decision 2026-07-21). Aviato's own `docs.yml` already does this (`push: branches: [main]` → empty version = dev); the MANAGED consumer docs callers (`aviato/library/scaffold/files/wf-docs-*.yml`) deploy only on a fresh release tag via the workflow_run gate, so consumer `dev` docs go stale between releases. Extend the consumer caller to also deploy `dev` when the completed default-branch CI run succeeded WITHOUT a release tag (keep the release-gated path and the §12/fork-origin protections unchanged; `dev` never moves `latest`). — source: 2026-07-21 pydmp pilot · aviato/library/scaffold/files/wf-docs-python-library.yml


## Settled — do not reopen

- Docs for ALL releases are kept — no pruning by default; `docs-retention` is an optional cap, default unlimited (#37, operator decision 2026-06-09).
- Zensical with built-in search is the only current docs baseline (operator decision 2026-07-11); prior Docusaurus and Algolia decisions are historical and superseded.
- §13.3 disposable-consumer Pages proof PROVEN 2026-07-17: branch DoD (version dir + `latest` symlink alias), served-site DoD (root/`latest`/versioned URLs 200, sitemap, search index, Mermaid rendering), and the §8.14 monotonic-alias DoD (minor release moves `latest`; old-line hand-tagged patch does not) all verified live on a disposable public repo, after fixing a real upstream bug (`reusable-docs-pages.yml` ran `git archive` under the docs working-directory instead of the repo root, silently producing an empty Pages artifact — fixed in aviato PR #85). See [traceability §13.3](../../../traceability.md) and the [2026-07-18 evidence record](../../../evidence/2026-07-18-deploy-proofs.md).
