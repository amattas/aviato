<!-- Split from ARCHITECTURE.md (2026-07-11). -->

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
