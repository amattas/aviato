# CLAUDE.md

## What this is

A copy-paste starter kit for amattas's repos — CI, tag-push releases,
Docusaurus docs, rulesets, Dependabot. `starter/` holds the master copies;
consumer repos carry their own copies of these files (vendored, never
referenced cross-repo — PyPI trusted publishing matches the workflow file
in-repo, and repos must not break when this one changes).

There is deliberately **no engine here**: no CLI, no package, no tests, no
drift automation. The previous incarnation of this repo was exactly that and
was stripped (see git history before the strip commit if needed).

## Working on the kit

- The kit files are MASTERS. A learning from a consumer repo (pydmp, hass-dmp,
  …) gets backported here so the next migration inherits it; keep masters and
  consumers byte-comparable where possible.
- Lint gate (same as CI): `yamllint -s .`, `actionlint` on
  `.github/workflows/*.yml starter/*/ci.yml starter/*/release.yml
  starter/docs-site/docs.yml`, `shellcheck starter/rulesets/apply-rulesets.sh`.
- Workflow conventions: job id `ci` is the required check everywhere; release
  workflows trigger only on digit-initiated tags (`["[0-9]*"]`) and create the
  GitHub release LAST; third-party actions digest-pinned, first-party on major
  tags; every `${{ }}` in run blocks goes through `env:`.
- The docs scaffold (`starter/docs-site/`) encodes hard-won MDX/Docusaurus
  fixes (per-mode prism themes, `mdx.format: md` for generated pages, the
  `<p>`-nesting hydration trap) — don't simplify them away.
- Releasing consumers: bump the version source, merge, `git tag X.Y.Z && git
  push origin X.Y.Z`. Never create releases via the GitHub UI (the tag it
  creates fires the workflow, which then collides with the existing release).
