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
