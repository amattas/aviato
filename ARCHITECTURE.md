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
- reusable caller workflow templates;
- GitHub repository ruleset payloads;
- operator-run scripts for auditing and applying rulesets;
- generated or local reporting artifacts.

The current implementation includes the day-zero workflow surface from
`REQUIREMENTS.md`, but not the full profile/scaffold/drift engine. That deeper
module system remains the next architecture layer.

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
- `reusable-node-ci.yml` runs Node install, lint, test, and build commands.
- `reusable-swift-ci.yml` runs Swift/Xcode lint, test, and build commands on
  macOS.
- `reusable-docker-ghcr.yml` publishes release images to GHCR.
- `reusable-pypi-publish.yml` publishes Python packages through PyPI trusted
  publishing.
- `reusable-docs-pages.yml` builds and publishes Docusaurus docs to GitHub
  Pages.
- `reusable-app-store-connect.yml` archives, signs, exports, and uploads Apple
  app builds to App Store Connect.
- `reusable-security-baseline.yml` provides CodeQL and dependency-review gates.
- `reusable-release-gate.yml` validates release tags before deployment or
  publishing workflows proceed.

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

### Caller Templates

Caller templates live in `templates/`. They are examples or starting points for
consumer repositories and are not the source of policy truth.

The templates should stay thin. They should select a reusable workflow, provide
repository-specific input values, and avoid duplicating release or protection
logic.

### Rulesets

Ruleset payloads live in `rulesets/`.

- `protect-default-branch.json` protects the repository default branch.
- `release-tag-format.json` protects release tags and enforces the release tag
  format.

Rulesets are applied by an operator command. The library may provide templates
and rendering logic, but protected settings are not silently mutated by
unattended automation.

The near-term shape is:

- `policy.yml` owns policy constants such as the release tag pattern.
- `rulesets.yml` declares which ruleset templates exist and how policy values
  are injected into them.
- ruleset JSON files remain readable templates.

### Scripts

The Python CLI lives in `aviato/`.

- `aviato audit <root>` discovers and audits repositories under a local root.
- `aviato audit --repo <path>` audits one local repository.
- `aviato apply-rulesets <owner/repo>` applies configured rulesets.
- `aviato render-rulesets` renders the ruleset payloads after policy injection.
- `aviato validate` validates this repository's policy infrastructure.
- `aviato onboard <path-or-owner/repo>` currently prints the onboarding plan for
  one explicit target.

Compatibility shell wrappers live in `scripts/`.

- `audit-repos.sh` discovers local repositories, reads GitHub state, evaluates
  policy status, and renders a tabular report by calling the CLI.
- `apply-rulesets.sh` creates or updates configured GitHub rulesets by calling
  the CLI.
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
^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta)[0-9]+)?$
```

Accepted examples:

- `1.2.3`
- `1.2.3-alpha1`
- `1.2.3-beta2`

Rejected examples:

- `v1.2.3`
- `1.2.3-beta.1`
- `build-20260519.0215`

The canonical file is `policy.yml`. Ruleset rendering derives from it, and
validation checks any embedded copies needed by GitHub Actions defaults.
Documentation may describe policy, but documentation must not become the source
of truth.

## Release Architecture

Release publishing is tag-driven only.

Release workflows must run from tags that match the canonical release format.
Legacy `release/*` branches and `release/latest` are migration artifacts and
should not be supported by release publishing workflows.

If branch or pull request Docker builds are needed, they should be implemented
as a separate non-release workflow instead of weakening the release workflow.

Release workflows embed release reference validation so the validation behavior
is pinned to the same ref as the reusable workflow. A standalone composite
validator also exists for direct callers that want it:

```text
.github/actions/validate-release-ref/action.yml
```

Repository validation checks those embedded patterns against `policy.yml`.

### App Store Connect Releases

Apple App Store Connect is the day-zero deployment target for the `swift-app`
profile.

The reusable workflow:

- run only from validated release tags;
- run on a macOS runner;
- require a protected deployment environment with required reviewers;
- load Apple signing and App Store Connect API secrets only in the deploy job;
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
- GitHub Actions workflow linting;
- YAML syntax for `policy.yml` and `rulesets.yml`;
- JSON syntax for `rulesets/*.json`;
- drift checks that compare embedded release tag patterns against `policy.yml`;
- Python tests once the CLI exists.

CI should install required validation tools and run the validation script on
pull requests and default-branch pushes.

## Non-Goals For The Current Implementation

- Persistent committed inventory of consumer repositories.
- Automatic unattended mutation of protected consumer repository settings.
- Multiple hosting-platform bindings.
- A full module/profile engine before the lightweight GitHub implementation is
stable.
- Release publishing from legacy release branches.
