# Starter kit — copy-paste CI/release for solo-dev repos

No engine, no CLI, no drift detection. Each repo carries its own copies of a few
small workflows; this folder is the master copy. Updating a repo = copying the
file again and reviewing the diff in a normal PR.

**Releasing is `git tag 1.2.3 && git push origin 1.2.3`.** The tag is the ship
decision. No release PRs, no version derivation. Bump the version in source
first; the release workflow refuses a tag that doesn't match.

## What to copy where

| Repo type | Copy from | Into the repo |
|---|---|---|
| Python library (publishes to PyPI) | `python-library/ci.yml`, `release.yml`, `dependabot.yml` | `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/dependabot.yml` |
| Python app/tool (no PyPI) | `python-app/` same three files | same destinations |
| Node service | `node-service/ci.yml`, `release.yml`, `dependabot.yml`, `npmrc` | same destinations; `npmrc` → `.npmrc` at repo root |
| Container service | `container-service/release.yml` **plus** the `ci.yml`+`dependabot.yml` for the repo's language | `.github/workflows/release.yml` |
| Docs site (Docusaurus) | `docs-site/docs.yml` → `.github/workflows/docs.yml`; everything else in `docs-site/` → `website/` (`npmrc` → `website/.npmrc`) | full site scaffold — see below |
| Swift app | `swift-app/ci.yml`, `dependabot.yml` | same destinations |

Every workflow has a `# CUSTOMIZE` comment block at the top listing the lines
you're expected to adjust (commands, paths, Python/Node versions).

### Docs-site scaffold (proven on pydmp)

`docs-site/` is a complete Docusaurus site, not just the deploy workflow:
self-hosted full-text search (no Algolia account), per-mode Prism themes
(Docusaurus's default is a dark palette in BOTH modes — unreadable on light),
browser-preference color mode, native doc versioning (latest release at the
site root, main at `/dev`, dropdown in the navbar), hardened `.npmrc`, IBM
Plex design system with a swappable accent palette, and a committed lockfile.
Fill the ALL-CAPS placeholders (`PROJECT`/`OWNER`/`REPO`), and gitignore
`website/{node_modules,build,.docusaurus}` + the generated API reference.
Python repos: uncomment the pydoc-markdown block in `docs.yml` for
docstring-generated API docs (the `mdx.format: md` front matter it writes is
load-bearing). Cutting a docs version joins each release-bump PR:
`cd website && npm run docusaurus docs:version X.Y.Z`.

## One-time setup per repo (clicks + one script, no automation)

1. **Rulesets:** `./rulesets/apply-rulesets.sh OWNER/REPO` — branch protection
   (PR required, `ci` check required, no force-push/deletion, admin bypass for
   emergencies) and tag protection (tags are immutable). Idempotent; re-run
   any time.
2. **CodeQL:** repo Settings → Code security → CodeQL analysis → Default setup.
   (Settings-based; needs no workflow file.)
3. **Pages** (docs sites only): Settings → Pages → Source: GitHub Actions.
4. **PyPI trusted publisher** (Python libraries only): pypi.org → Publishing →
   publisher with workflow **`release.yml`** and environment **`release`**.
   PyPI matches the workflow file that contains the publish step plus the
   environment — that's why the workflow must live in the repo itself, and why
   this kit vendors files instead of referencing shared workflows cross-repo.
   Repos with an older registration (different filename/environment): update
   the registration to `release.yml` + `release` during migration.

## Conventions baked in

- Tag format: `X.Y.Z` with optional `-alphaN`/`-betaN` (prereleases get marked
  as such on the GitHub release).
- The GitHub release is created **last**, after publishing succeeds — published
  immediately (not draft) with auto-generated notes; edit afterwards if needed.
- Third-party actions are digest-pinned; first-party (`actions/*`, `github/*`)
  ride major tags. Dependabot bumps both weekly.
- pip-installed tools in workflows are exact-pinned (`build==1.5.0`,
  `twine==6.2.0`).
- Container releases are multi-arch (amd64 + arm64 on native runners, for ARM
  k8s nodes); each arch is scanned before its bytes are pushed, then a manifest
  ties them together. Single-arch repos delete one matrix entry.
- Docs are Docusaurus everywhere — repos still on mkdocs convert as part of
  their migration; there is deliberately no mkdocs flavor.
