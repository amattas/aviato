# Starter kit — normative conventions

The starter kit (`starter/`) is the vendored, no-engine distribution: each
consumer repo carries its own copies of the kit workflows; `starter/` holds the
masters. These decisions are normative for the kit and its consumers.

- **Releasing is a tag push.** `git tag X.Y.Z && git push origin X.Y.Z` is the
  ship decision — no release PRs, no version derivation. The workflow refuses a
  tag that doesn't match the version in source. Release triggers only on
  digit-initiated tags. Never create releases via the GitHub UI (tag collision
  with the workflow).
- Tag format `X.Y.Z` with optional `-alphaN`/`-betaN` (prereleases marked on the
  GitHub release). The GitHub release is created **last**, after publishing.
- Required check context is the job id `ci`; rulesets applied once via
  `starter/rulesets/apply-rulesets.sh` (idempotent).
- **All three PR merge methods are allowed** (merge commit, squash, rebase),
  normalized on every managed repo by `apply-rulesets.sh` for a consistent merge
  UI across the fleet (2026-07-11 operator decision).
- **Workflows are vendored, not referenced cross-repo.** PyPI trusted publishing
  matches the workflow file containing the publish step (`release.yml`) plus the
  `release` environment — structurally impossible through a shared cross-repo
  reusable workflow (FINDINGS F-3).
- Third-party actions digest-pinned; first-party ride major tags; pip tools in
  workflows exact-pinned. Dependabot bumps weekly.
- Container releases are multi-arch (amd64 + arm64 on native runners); each arch
  scanned before its bytes are pushed, then a manifest ties them together.
- Docs are Zensical everywhere, versioned onto a docs branch (default
  `gh-pages`) via a mike fork; docs deploy on release tags. GitHub Pages
  serving of that branch is a separate, optional operator toggle.
- Learnings from consumer repos are backported to the kit masters.
- **Agent guidance merges; managed skills replace.** The kit's `CLAUDE.md` and
  `AGENTS.md` templates carry one byte-identical marked governance block. An
  existing consumer file preserves project-specific text and replaces only
  that block. The four named starter skills (`docs-structure`, `traceability`,
  `docs-reconciliation`, `test-consolidation`) replace atomically after local
  drift review; unknown skills are untouched and deliberate customizations use
  a different name.
- **Living records are seed-once.** The traceability matrix and living
  requirements, specifications, architecture, and security docs are created
  only when absent, then reconciled semantically—never reset from templates.
- Completed work leaves backlog `Open` after its requirement and traceability
  state are current. Dated plans are pruned after every durable fact is promoted
  to living documentation; plans never become the project system of record.
- Correctness and local verification precede publishing. Coherent changes may
  share one branch and pull request to avoid redundant CI runs, but cost does
  not weaken tests, security gates, review, release controls, or evidence.
