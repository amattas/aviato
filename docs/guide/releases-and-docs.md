# Releases and docs

How a managed repository cuts a release and how its documentation is versioned.
Both flows are tag-only and operator-gated at the publish boundary.

## The release model

Releases are driven by [Conventional Commits](https://www.conventionalcommits.org/):

1. Merged commits determine the next version through the §5.9 bump
   (`aviato next-version`). When a bump is warranted, the release automation opens
   a `chore(release): X.Y.Z` PR that stages the version change.
2. Merging that PR **cuts the tag in the same run** — the tag is created from the
   merged commit rather than pushed by hand.
3. The tagged run passes a **release gate** that validates the commit before any
   outward publish.
4. The **publish jobs** (PyPI, GHCR, Pages, Apple) run only on that tag and are
   gated by the `pypi` (or equivalent) environment's required-reviewer approval.
   No publishing credential is stored — PyPI uses Trusted Publishing OIDC bound to
   the consumer's `aviato-ci.yml` workflow and `pypi` environment.

**Release publishing is tag-only.** Tags must match the policy pattern with no
`v` prefix (`1.2.3`, `1.2.3-alpha1`, `1.2.3-beta2`); legacy `release/*` publish
branches are a migration artifact and are rejected by validation. See the
[release specification](../specifications/modules/versioning/release.md) for the
precise flow.

## The versioned-docs model

Docs are opt-in (`docs: true`, default off) and built with **Zensical**, versioned
onto a dedicated docs branch (default `gh-pages`) through a **mike fork**. The full
model is in the
[docs-site requirements](../specifications/modules/deployment/docs-site/requirements.md);
the operator-facing shape is:

- **Trigger is the version tag only.** Each policy-conformant release deploys its
  own `X.Y.Z` version directory to `gh-pages`. Entries are **per release** — one
  directory per `X.Y.Z`, not per minor.
- **The `latest` alias and default version move only when the release is the
  highest** released version, enforced by the §8.14 monotonic guard (fail-closed:
  an unlistable tag set skips the deploy rather than mis-moving the alias).
- **Retention keeps every version by default.** `docs-retention` defaults to 0
  (unlimited); an operator may set N>0 to prune to the newest N versions via
  `mike delete` on each release.
- **The version selector in the site header is populated from `versions.json`** on
  the docs branch, so readers can switch between released versions.

### Serving the docs

Producing the docs branch needs no operator prerequisite. To **serve** it, set the
non-secret variable `serve-pages: true` and point Pages at the workflow build type
(never Deploy-from-a-branch):

```bash
gh api --method PUT repos/OWNER/REPO/pages -f build_type=workflow
gh api repos/OWNER/REPO/pages
```

The auth split is by design: the build job runs consumer emit code with read-only
scopes, and a separate no-consumer-code push job fast-forwards the docs branch. A
release is docs-verified from the branch alone — the new `X.Y.Z` directory exists
and the `latest` alias moved iff this release is the highest.

See [getting started](getting-started.md) for the one-time environment and Pages
setup, and the [CLI reference](cli.md) for `next-version`, `bump-version`, and
`is-highest`.
