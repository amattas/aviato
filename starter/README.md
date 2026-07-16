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
| Docs site (Zensical) | `docs-site/docs.yml` → `.github/workflows/docs.yml`; `zensical.toml` → repo root; `requirements.txt` → `requirements-docs.txt` at repo root; `docs/` → `docs/` | full site scaffold — see below |
| Swift app | `swift-app/ci.yml`, `dependabot.yml` | same destinations |

Every workflow has a `# CUSTOMIZE` comment block at the top listing the lines
you're expected to adjust (commands, paths, Python/Node versions).

### Docs-site scaffold

`docs-site/` is a complete Zensical site, not just the deploy workflow:
built-in full-text search and Mermaid diagram support, no separate npm
toolchain. Versioning is via `mike`, deployed onto the `gh-pages` branch — the
`latest` alias lives at the root, `dev` deploys from every push to `main`, and
each release tag additionally deploys its exact version (`mike` moves `latest`
only when the tag is the highest release; older tags land under their own
version path without touching `latest`). The site lives at the repo root:
`zensical.toml` next to `pyproject.toml`/`package.json`, content in `docs/`.
Fill the ALL-CAPS placeholders in `zensical.toml` (`PROJECT`/`OWNER`/`REPO`),
and gitignore `site/` (the local build output dir). One-time: repo Settings →
Pages → Source: Deploy from a branch → `gh-pages`. Python repos: uncomment the
pydoc-markdown block in `docs.yml` for docstring-generated API docs.

### Migrating a Docusaurus docs site

1. Move `website/docs/` to `docs/` at the repo root, then delete `website/`
   (`package.json`, `package-lock.json`, `docusaurus.config.js`, `sidebars.js`,
   `.npmrc`, `src`, …).
2. Add `zensical.toml` (repo root) + `requirements.txt` (→ `requirements-docs.txt`)
   from this kit.
3. Swap in the new `docs.yml`.
4. Delete `versioned_docs/`, `versioned_sidebars/`, `versions.json` — version
   history now lives on the `gh-pages` branch via `mike`, not in the source tree.
5. Set Pages source to **Deploy from a branch → `gh-pages`** (Settings → Pages)
   so Pages serves the versioned branch mike maintains.
6. Then run once, from the repo root, to seed `gh-pages` with the existing
   history: `mike deploy --push <current-release> latest && mike set-default
   --push latest && mike deploy --push dev`.

### Agent guidance and repo-local skills (any repo)

Copy the governance pack once when adopting the starter:

| Starter master | Consumer destination | Update behavior |
|---|---|---|
| `starter/CLAUDE.md` | `CLAUDE.md` | Create when missing; otherwise merge only the marked managed block |
| `starter/AGENTS.md` | `AGENTS.md` | Create when missing; otherwise merge only the marked managed block |
| `starter/skills/<name>/` | `.claude/skills/<name>/` | Replace the whole managed skill directory after drift review |
| `starter/docs/requirements/traceability.md` | `docs/requirements/traceability.md` | Seed-once; maintain content, never replace it with the blank template |

The managed skills are `docs-structure`, `traceability`,
`docs-reconciliation`, and `test-consolidation`. Claude Code discovers the
canonical `.claude/skills/` copies; `AGENTS.md` directs Codex and other agents
to read the same files, avoiding duplicated skill bodies.

On an update, preserve every unknown/project-local skill. If a managed skill
has local modifications, stop for an operator decision: accept the canonical
replacement or fork the customization under a different skill name. Never
line-merge a skill. Existing agent files keep all project-specific content
outside `aviato:documentation-governance` markers; replace only that managed
block. Living documentation and the traceability matrix remain seed-once.

## One-time setup per repo (clicks + one script, no automation)

1. **Rulesets:** `./rulesets/apply-rulesets.sh OWNER/REPO` — branch protection
   (PR required, `ci` check required, no force-push/deletion, admin bypass for
   emergencies) and tag protection (tags are immutable). Also normalizes PR
   merge methods (all three — merge/squash/rebase — allowed). Idempotent; re-run
   any time.
2. **CodeQL:** repo Settings → Code security → CodeQL analysis → Default setup.
   (Settings-based; needs no workflow file.)
3. **Pages (docs sites only):** Settings → Pages → Source: **GitHub Actions**.
   Never select Deploy from a branch: the workflow first archives the versioned
   `gh-pages` state, then deploys that exact tree through Pages Actions in the
   same non-cancelling run.
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
- Docs are Zensical everywhere (2026-07-11 decision, supersedes
  Docusaurus-everywhere); repos on Docusaurus/mkdocs convert during migration.
