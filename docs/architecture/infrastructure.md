<!-- Split from ARCHITECTURE.md (2026-07-11). -->

## Current Components

### Reusable Workflows

Reusable workflows live in `.github/workflows` and are consumed through
`workflow_call`.

- `reusable-python-ci.yml` runs Python install, lint, and test commands.
- `reusable-node-ci.yml` runs Node install, lint, test, and build commands;
  defaults to Node 24; and blocks npm <11.10 (the `min-release-age` support
  floor) before install so `min-release-age=7` and `ignore-scripts=true` are
  enforceable. Its default Node tool invocations use `npx --no-install`.
- `reusable-common-lint.yml` runs the same `aviato lint-actions` implementation
  as `aviato validate` (no second copy to drift), including unsafe plain `npx`
  detection, so consumers fail in CI on supply-chain drift.
- `reusable-swift-ci.yml` runs Swift/Xcode lint, test, and build commands on
  macOS.
- `reusable-docker-ghcr.yml` builds and Trivy-scans OCI archives, then promotes
  the exact scanned archives to GHCR by digest — no rebuild between scan and
  push. The publish job runs in a deployment environment (default `ghcr`).
- `reusable-pypi-publish.yml` publishes Python packages through PyPI trusted
  publishing; the publish job runs in a deployment environment (default
  `pypi`).
- `reusable-docs-pages.yml` installs with the same npm hardening, lints the
  Docusaurus site, versions it, and publishes it to GitHub Pages. Its
  `docs-retention` input defaults to 0, which keeps every released version's
  docs.
- `reusable-app-store-connect.yml` archives, signs, exports, and uploads Apple
  app builds to App Store Connect.
- `reusable-security-baseline.yml` provides CodeQL and dependency-review gates.
- `reusable-release.yml` derives the next version from Conventional Commits and
  cuts the release (release PR, then tag + GitHub release), split into a
  read-only derive job and a write release job.
- `reusable-release-gate.yml` validates release tags before deployment or
  publishing workflows proceed and exports the validated commit as a
  `gated-sha` output; deploy workflows check out that exact commit — never the
  mutable tag — and re-verify the tag still points at it before publishing.
- `reusable-consumer-automation.yml` runs the scheduled drift report: it opens
  file-drift proposals and files settings-drift tracking issues, and never
  mutates protected settings.

The CI workflows use a common language-module contract:

- `working-directory`
- `install-command`
- `lint-command`
- `test-command`
- `build-command`
- `run-install`
- `run-lint`
- `run-tests`
- `run-build`

Every language workflow should expose the same input names. Unsupported steps
use an empty command and a disabled default.

Docs-enabled profiles scaffold a Docusaurus `website/` with the first-party
Docusaurus ESLint plugin, opt-in Algolia search (enabled via the `algolia`
profile variable; default off), Mermaid rendering, and sitemap configuration
through the classic preset. Node and docs scaffolds include managed `.npmrc`
files with the npm supply-chain defaults and package engines requiring
Node 24/npm >=11.10.

### Caller Templates

Caller templates live in `templates/`. They are examples or starting points for
consumer repositories and are not the source of policy truth. They are **rendered
from** the authoritative scaffold bundles (`aviato/library/scaffold/files/wf-*.yml`)
via `scripts/regen-templates.py`; `aviato validate` fails if they drift.
Committed examples use `EXAMPLE_PIN`; fresh onboarding/provisioning requires an
explicit published Library pin, with `--allow-unresolved-pin` reserved for
intentional offline/test scaffolds.

The templates should stay thin. They should select a reusable workflow, provide
repository-specific input values, and avoid duplicating release or protection
logic.

### Rulesets

Ruleset payloads live in `aviato/library/rulesets/` (inside the package, so they
ship in the wheel for installed rendering).

- `protect-default-branch.json` protects the repository default branch.
- `release-tag-format.json` protects release tags and enforces the release tag
  format.

Rulesets are applied by an operator command. The library may provide templates
and rendering logic, but protected settings are not silently mutated by
unattended automation.

The near-term shape is:

- `aviato/library/policy.yml` owns policy constants such as the release tag pattern.
- `aviato/library/rulesets.yml` declares which ruleset templates exist and how policy
  values are injected into them.
- ruleset JSON files remain readable templates.

### Core Engine

The agnostic core lives in `aviato/core/` and knows how to resolve, compose,
scaffold, diagnose, and reconcile — with **no** language- or
deployment-specific logic. Its falsifiable agnosticism (§9b) is enforced by
`aviato/core/selfcheck.py` (no import edge into `aviato/plugins/`, no denylisted
identifier from `aviato/plugins/denylist.txt`) and checked as part of
`aviato validate`. Day-zero plug-in specifics live as **data** under `aviato/library/`
(the §5.10 module-source tree: `aviato/library/<profile>.yaml`, `aviato/library/bundles/`,
`aviato/library/scaffold/`), loaded by `aviato/core/registry.py`. See `CLAUDE.md` for the module map.

Supply-chain pin enforcement (§11.3) is a plug-in concern. `uses:`/container-image pinning is
delegated to **zizmor** (a pinned dependency) configured by bundled policy data at
`aviato/library/zizmor.yml`; `curl|bash` fetch-execute uses a **fail-closed** rule (reject anything
not provably checksum-verified or piped to an allowlisted data sink — deliberately *not* an
interpreter enumeration, which fails open). Both run through the one `aviato lint-actions`
entrypoint, invoked identically by `aviato validate` and by every consumer's `reusable-common-lint`
CI — a single implementation, no grep mirror.

The Library consumes itself through the internal `aviato-library` profile and a
declaration that sets `bootstrap: true`. Bootstrap rendering is validated against
every managed artifact resolved by that declaration, and local workflow/install
references are accepted only on this structural Library path.

### Scripts

The Python CLI lives in `aviato/`.

- `aviato audit <root>` discovers and audits repositories under a local root.
- `aviato audit --repo <path>` audits one local repository.
- `aviato apply-rulesets <owner/repo>` applies configured rulesets (dry-run by
  default; `--apply` mutates). `--declaration <path>` resolves status checks
  and approvals through a consumer's `.github/aviato.yaml` overrides so an
  apply never re-adds a check the consumer removed.
- `aviato render-rulesets` renders the ruleset payloads after policy injection.
- `aviato validate` validates this repository's policy infrastructure.
- `aviato onboard <path-or-owner/repo>` prints the composition-backed onboarding
  plan (pipelines, templates, variables, settings) for one explicit target;
  `--write` adopts a local repo, `--open-pr` adopts an existing repo through a
  reviewable scaffold PR, and `--docs` composes the opt-in docs deploy. Fresh
  writes require `--pin`; onboarding preserves an existing pin and directs pin
  movement to `aviato repin`.
- `aviato provision <owner/repo>` creates and scaffolds a new consumer repository
  with staged protection; it also requires an explicit published pin and
  accepts `--docs`.
- `aviato doctor <path>` classifies a consumer's managed artifacts (§5.4).
- `aviato sync <path>` materializes managed/seed-once artifacts into a consumer
  repository from its declaration (§5.3).
- `aviato scan <paths...>` diagnoses many local consumer repositories
  (read-only); `--fix` opens managed-file proposals and `--audit` also surfaces
  each repo's open settings-drift tracking issue (§5.11).
- `aviato drift-report <path>` reports file + settings drift for one consumer
  (`--file-only`, `--settings-only`, `--require-settings`) (§5.5/§5.6).
- `aviato reconcile <path> <issue> --confirm <diff-id>` applies settings from a
  tracking issue — operator-gated and diff-bound (§5.7).
- `aviato complete-protection <path>` idempotently (re-)applies full branch
  protection (§5.2 recovery).
- `aviato repin <path> <version>` moves the Library version pin: `--write`
  mutates locally, `--open-pr` opens a reviewable re-pin proposal (§5.12).
- `aviato offboard <path>` removes a consumer from Aviato management:
  `--write` (optionally `--delete-files`) mutates locally, `--open-pr` opens a
  reviewable removal proposal (§5.13).
- `aviato next-version --current X.Y.Z --commit "..."` derives the next SemVer
  from Conventional Commits (§5.9).
- `aviato bump-version <version> <path>` writes a version into the
  version-source locations (§3.3).
- `aviato is-highest <candidate> <existing...>` exits 0 iff the candidate is
  the highest release (§8.14 alias gate).
- `aviato lint-actions [path]` runs the §11.3 supply-chain pinning gate (zizmor
  for `uses:`/images plus the fail-closed `curl|bash` check).

Compatibility shell wrappers live in `scripts/`.

- `audit-repos.sh` discovers local repositories, reads GitHub state, evaluates
  policy status, and renders a tabular report by calling the CLI.
- `apply-rulesets.sh` creates or updates configured GitHub rulesets by calling
  the CLI (dry-run by default; `--apply` mutates).
- `validate.sh` runs repository validation and local tests.

### Local Reports

Audit reports and repo lists are operator artifacts, not library state. Files
such as `catalog.md` or a local repo list can exist during a rollout, but they
should be treated as generated or local working files rather than committed
architecture.
