# Aviato Architecture

This document describes the current lightweight architecture of this repository
and the near-term direction agreed for making it more consistent and modular.
`REQUIREMENTS.md` remains the broader requirements document; this file is the
implementation-facing map of what Aviato is today.

## Purpose

Aviato is a reusable GitHub policy, CI, release, and onboarding conventions
library. It provides shared building blocks that can be consumed by many
repositories without requiring this library to keep a persistent registry of
those consumers.

The current implementation is intentionally small:

- reusable GitHub Actions workflows;
- reusable caller workflow templates and composition-backed scaffold bodies;
- GitHub repository ruleset payloads;
- operator-run scripts for auditing and applying rulesets;
- generated or local reporting artifacts.

The current implementation includes the day-zero workflow surface from
`REQUIREMENTS.md` **and** the agnostic core engine (`aviato/core/`): profile
resolution/composition, the consumer declaration contract, managed-marker
scaffolding with seed-once, diagnosis, file/settings drift, the fail-closed
authorization gate, version-pin compatibility, bootstrap detection, Conventional
Commit version derivation, onboarding/sync, re-pin, and offboarding. The
*platform-side* orchestration of the §5.5–§5.7/§5.9 flows is implemented as
well: opening proposals, filing tracking issues, applying settings, and cutting
releases live in `aviato/core/` (`file_drift_flow`, `settings_drift_flow`,
`reconcile_flow`, `fleet`) behind the `aviato/github_platform.py` binding, and
are surfaced through the `drift-report`/`reconcile`/`scan` CLI commands and the
`reusable-consumer-automation.yml`/`reusable-release.yml` workflows. What
remains is live end-to-end operator verification of those flows against a real
GitHub repository — the engine primitives and the binding's response-mapping
are unit-tested.

## Boundaries

The library owns reusable policy and automation. It should not own consumer
inventory.

Consumer repositories adopt Aviato by referencing reusable workflows, copying or
generating caller workflow files, and having rulesets applied by an
operator-initiated command.

The operator runs privileged commands from a local workstation. Audits may
discover repositories from a local root or target one explicit repository.
Onboarding should target explicit repositories. Persistent fleet inventory is
not part of the library contract.

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

## Policy Source

Policy constants should have one canonical source.

The release tag format is:

```text
^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(alpha|beta)[0-9]+)?$
```

Accepted examples:

- `1.2.3`
- `1.2.3-alpha1`
- `1.2.3-beta2`

Rejected examples:

- `v1.2.3` (no `v` prefix allowed)
- `1.2.3-beta.1`
- `build-20260519.0215`

The canonical file is `aviato/library/policy.yml`. Ruleset rendering derives from it, and
validation checks any embedded copies needed by GitHub Actions defaults.
Documentation may describe policy, but documentation must not become the source
of truth.

## Release Architecture

Release publishing is tag-driven only.

Release workflows must run from tags that match the canonical release format.
Branch-based release *publishing* (legacy `release/*` / `release/latest` publish
branches) is a migration artifact and is rejected by validation. This is distinct
from the release-PR *source* branch (`reusable-release.yml` opens its proposal on a
short-lived `release/<version>` branch and tags from the default branch) — that is
not branch-based publishing and is allowed.

If branch or pull request Docker builds are needed, they should be implemented
as a separate non-release workflow instead of weakening the release workflow.

Release workflows embed release reference validation inline (a `TAG_PATTERN` env
fed to the ref check) so the validation behavior is pinned to the same ref as the
reusable workflow.

Repository validation checks those embedded patterns against `policy.yml`.

### App Store Connect Releases

Apple App Store Connect is the day-zero deployment target for the `swift-app`
profile.

The reusable workflow:

- run only from validated release tags;
- run on a macOS runner;
- require a protected deployment environment with required reviewers;
- load Apple signing and App Store Connect API secrets only in the deploy job;
- scope Apple secrets to the specific steps that need them, after any
  caller-controlled version command has already run;
- build and archive with Xcode;
- export a signed distributable;
- upload to App Store Connect / TestFlight;
- optionally submit for review when explicitly configured;
- record an operator-checkable upload artifact such as the App Store Connect
  build ID or upload receipt.

The caller template collects repository-specific values such as
scheme, workspace or project path, bundle identifier, team ID, export method,
monotonic build number source, and protected environment name.

## Branch Protection Architecture

The architecture uses "default branch" terminology. `main` is only an example
default branch name.

Rulesets should target GitHub's `~DEFAULT_BRANCH` selector where possible.
Reports and command output should use names such as
`default_branch_requires_pr`, not `main_requires_pr`.

## Validation

This repository should validate itself because it is policy infrastructure.

The validation entrypoint is:

```bash
./scripts/validate.sh
```

Validation should cover:

- shell syntax and linting while shell scripts remain;
- Ruff lint/format plus Black compatibility for the Library source tree;
- strict mypy type-checking of the Library package (the Library's own
  declaration sets `run-typecheck: true`);
- GitHub Actions workflow linting;
- YAML syntax for `aviato/library/policy.yml` and `aviato/library/rulesets.yml`;
- JSON syntax for `aviato/library/rulesets/*.json`;
- drift checks that compare embedded release tag patterns against `policy.yml`,
  and that the inline `highest.py` monotonic-alias guards embedded in the deploy
  workflows still agree with the core `is_highest` comparator (§8.14/§13.2);
- bootstrap checks that the Library declaration resolves every expected managed
  artifact through local self-reference and that none use released refs;
- workflow guard tests for npm install hardening, docs linting, App Store secret
  scoping, and `local-install` bootstrap confinement;
- the Python test suite (`pytest`).

CI should install required validation tools and run the validation script on
pull requests and default-branch pushes.

## Non-Goals For The Current Implementation

- Persistent committed inventory of consumer repositories.
- Automatic unattended mutation of protected consumer repository settings.
- Multiple hosting-platform bindings.
- Release publishing from legacy release branches.
