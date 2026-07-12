# Docs stack rework: Docusaurus → Zensical — design

**Date:** 2026-07-11
**Status:** approved (brainstorm 2026-07-11)
**Operator decisions recorded here:** versioning = mike + gh-pages; scope = everything
(kit + engine plug-in + this repo's site). This supersedes two settled decisions —
G1 "Docusaurus everywhere" and "Algolia stays, configurable" — and must land the
superseding entries in the affected Settled ledgers (anti-fickleness doctrine).

## Goal

Replace Docusaurus with Zensical (the Material-for-MkDocs team's successor SSG)
across: the starter kit docs-site scaffold, the engine docs plug-in (§13.3 +
`reusable-docs-pages.yml` + scaffold bundle + wf-docs callers), and this repo's
own `website/`. Same principles: versioned docs for every release, search,
Mermaid, hardened supply chain, tag-push deploys, monotonic `latest`.

## Why / key facts (verified 2026-07-11)

- Zensical: pip-installed, Rust core, `zensical.toml` config (reads `mkdocs.yml`
  for migration), MIT. Search, Mermaid, admonitions **built in**. Pre-1.0
  (v0.0.50) — exact pin + Dependabot required.
- Versioning: Zensical's blessed path is the squidfunk **mike fork**, installed
  from git only (not on PyPI) — `pip install git+https://github.com/squidfunk/mike.git@<full-sha>`.
  Versions deploy as subpaths on a **gh-pages branch**; root redirects to the
  default alias. Bridge solution until native versioning ships.
- pydoc-markdown emits plain markdown — retained at 4.8.2; drop the
  Docusaurus-specific `mdx.format: md` front matter from the emit step.

## Toolchain & layout

- Docs deps are pip-only, pinned in `website/requirements.txt`:
  `zensical==<exact>`, `mike @ git+https://github.com/squidfunk/mike.git@<full-sha>`,
  `pydoc-markdown==4.8.2` (Python profiles). Dependabot pip ecosystem covers
  `/website` (and consumers' scaffolds seed the same).
- Project dir stays `website/` (`website/zensical.toml`, `website/docs/`,
  output `website/site/` gitignored) — never collides with the repo-level
  `docs/` requirements tree.
- Node/npm leave the docs path entirely: delete docs `package.json`,
  `package-lock.json`, `.npmrc`, ESLint config/plugin, Prism CSS, sidebars.js.
- `zensical.toml` baseline: site metadata vars (`PROJECT`/`OWNER`/`REPO`
  threading as today), `[project.extra.version] provider = "mike"`,
  `default = "latest"`, `alias = true`. No Algolia block — search is built in;
  the `algolia*` profile variables and the algolia config-template variant are
  deleted. Scaffold docs templates collapse 7 → 3
  (`zensical.toml`, `docs/index.md`, `requirements.txt`).

## Deploy & versioning model

- Tag push (policy-conformant, gated as today) →
  `mike deploy --push X.Y.Z latest --update-aliases`, where the existing §8.14
  monotonic guard decides whether `latest` moves (alias update skipped when the
  tag is not the highest release). `mike set-default latest` idempotently.
- Main push → `mike deploy --push dev`.
- All release versions are kept — preserves the recorded keep-all-releases
  decision (`docs-retention` cap remains available: prune via `mike delete`).
- **Branch-only deploy; Pages is decoupled and optional.** The workflow's sole
  output is commits to a docs branch (`docs-branch` input, default `gh-pages`)
  via `mike --branch`. It never reads or mutates Pages settings and succeeds
  identically whether Pages is enabled or not — serving is a per-repo operator
  toggle (Settings → Pages → deploy from branch), flippable on/off at any time
  without touching the workflow. Documented in the starter README setup
  section as an optional step.
- **Privilege change:** the `docs-pages` pipeline moves from
  `pages:write + id-token:write` to `contents: write` (pushes the docs
  branch); `aviato/library/pipelines.yaml` updated. Rulesets are unaffected
  (they target the default branch + release tags).
- §11.3 pip-pin gate: extended so a `git+…@<40-hex-sha>` pin **passes as exact**
  (and a branch/tag/short ref still fails). No exemption — fail-closed stays.

## Per-layer changes

**Engine** (pipeline name `docs-pages` is kept — profile YAML and the two
composition tests don't churn):
- `reusable-docs-pages.yml` rewritten: setup-python, pinned pip install from the
  consumer's `website/requirements.txt` (fallback: explicit pinned install
  inputs), optional `docs-emit-command` (pydoc-markdown), `zensical build` as a
  PR-facing check where applicable, mike deploy steps with the monotonic-alias
  snippet (still covered by `_check_monotonic_alias_parity`). npm-hardening
  steps deleted. Inputs simplified (drop node-version/npm floors; add
  `docs-requirements` path input).
- Scaffold metadata YAMLs: replace docusaurus-config/docusaurus-config-algolia/
  docs-package/docs-sidebars/docs-eslint-config/docs-npmrc with zensical-toml
  (seed-once), docs-index (seed-once), docs-requirements (managed, auto-updated).
- 5 `wf-docs-*.yml` scaffold caller bodies rewritten; `templates/` regenerated
  via `scripts/regen-templates.py`; `aviato-docs.yml` (self-docs caller) follows.
- Profile YAML: remove `algolia*` variables (6 profiles); `docs_pipeline:
  docs-pages` unchanged.
- Denylist: keep `docusaurus`, add `zensical` (+ `mike` is too generic — do NOT
  add it). Core remains agnostic; §9b tests updated only where they assert the
  denylist contents.
- Validation: keep pydoc-markdown pin parity; add zensical + mike pin parity
  across wf-docs callers and `website/requirements.txt` (same mechanism);
  REQUIRED_FILES updated for renamed/removed scaffold files.

**Starter kit:**
- `starter/docs-site/` replaced: `zensical.toml`, `docs/index.md`,
  `requirements.txt`, mike-based `docs.yml` (tag → version deploy; main → dev),
  with the same digit-initiated-tag and version-source guards as the other kit
  workflows. Default Zensical theme (IBM Plex custom design dropped — lighter
  is the point; theming returns later as `zensical.toml` options if wanted).
  Committed lockfile concept n/a (pip pins are the lock).
- `starter/README.md`: docs-site section rewritten (copy set, Pages source =
  gh-pages branch, PyPI-style one-time steps unchanged elsewhere), plus a
  **Docusaurus → Zensical migration recipe** for already-migrated repos
  (pydmp): delete website node artifacts, add zensical.toml + requirements.txt,
  keep the markdown, swap `docs.yml`, flip Pages source, initial
  `mike deploy --push <current> latest` + `mike deploy --push dev`.

**This repo:** `website/` converted in place (same content; delete node files,
add `zensical.toml` + `requirements.txt`); `.gitignore` swaps
`website/{build,.docusaurus}` for `website/site`.

**Docs & ledgers:**
- §13.3 (`docs/requirements/modules/deployment/docs-site/requirements.md`)
  rewritten for Zensical (stages, DoD: version present on the docs branch with
  correct alias state after deploy; and — when the operator has Pages enabled —
  latest resolves, built-in search returns results, Mermaid renders, sitemap
  present. The served-site checks are conditional on Pages being on.)
- Settled entries added (docs-site + starter-kit backlogs): "Zensical
  everywhere — supersedes G1 Docusaurus-everywhere and Algolia-configurable
  (operator decision 2026-07-11)". Open backlog entry added: "replace the mike
  bridge when Zensical ships native versioning".
- `docs/architecture/infrastructure.md` + `data-flow.md` mentions updated.

## Testing & done-bar

- TDD where the change is behavioral: pin-gate acceptance of full-SHA `git+`
  pins (new negative + positive cases), zensical/mike pin-parity check,
  denylist addition, scaffold composition (docs=true seeds the 3 new files, no
  algolia variant anywhere).
- Full gate green: `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh` (includes
  regen-templates parity, monotonic-alias parity, zizmor, actionlint).
- Local `zensical build` of `website/` and of the starter scaffold must succeed
  (real end-to-end build, not just config lint).
- Live mike deploys remain **operator-verified by design** (§9.2-style), same
  as every deploy pipeline: first real run happens on this repo's own docs.

## Non-goals

- No native-Zensical-versioning speculation (mike is the bridge; backlog entry
  tracks it). No theming work. No fleet PRs from this repo (kit is copy-paste
  by design; OVERLAY.md updates are operator working notes).
