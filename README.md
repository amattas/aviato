<p align="center">
  <img src="docs/assets/aviato-logo.svg" alt="Aviato — Where code takes flight" width="520">
</p>

# Aviato

Aviato is a reusable GitHub policy, CI, release, and onboarding conventions
library. It centralizes shared workflows, rulesets, and operator tooling without
keeping a committed inventory of consumer repositories.

## Policy

`policy.yml` is the canonical source for policy constants.

Release tags must match:

```text
^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta)[0-9]+)?$
```

Accepted examples: `1.2.3`, `1.2.3-alpha1`, `1.2.3-beta2`.

Rejected examples: `v1.2.3`, `1.2.3-beta.1`,
`build-20260519.0215`.

Release publishing is tag-only. Legacy `release/*` branches should be cleaned up
in consumer repositories rather than supported by release publish workflows.

## What Is Here

- `policy.yml` - canonical policy constants.
- `rulesets.yml` - ruleset manifest.
- `rulesets/*.json` - GitHub ruleset templates.
- `.github/actions/validate-release-ref` - shared release-tag validator.
- `.github/workflows/reusable-*.yml` - reusable CI, release, deploy, and security workflows.
- `templates/*.yml` - thin caller workflow templates for consumer repos.
- `aviato/` - Python CLI implementation.
- `scripts/*.sh` - compatibility wrappers and validation entrypoints.

## Commands

Install locally:

```bash
python3 -m pip install -e .[dev]
```

Audit repositories under a local root:

```bash
aviato audit .
```

Audit one repository:

```bash
aviato audit --repo /Users/amattas/GitHub/example
```

Dry-run rulesets:

```bash
aviato apply-rulesets amattas/example
```

Apply rulesets:

```bash
aviato apply-rulesets amattas/example --apply
```

Override required PR approvals for a solo repo:

```bash
aviato apply-rulesets amattas/example --required-approvals 0 --apply
```

Validate this repository:

```bash
./scripts/validate.sh
```

The legacy script names still work:

```bash
./scripts/audit-repos.sh .
./scripts/apply-rulesets.sh --repo amattas/example --apply
```

## Reusable Workflows

- `reusable-python-ci.yml`
- `reusable-node-ci.yml`
- `reusable-swift-ci.yml`
- `reusable-release-gate.yml`
- `reusable-docker-ghcr.yml`
- `reusable-pypi-publish.yml`
- `reusable-docs-pages.yml`
- `reusable-app-store-connect.yml`
- `reusable-security-baseline.yml`

Language CI workflows share the same command contract:

- `working-directory`
- `install-command`
- `lint-command`
- `test-command`
- `build-command`
- `run-install`
- `run-lint`
- `run-tests`
- `run-build`

## Profile Templates

The `templates/profile-*.yml` files compose CI, security, release validation,
and deployment jobs for common repo shapes:

- `profile-python-service.yml`
- `profile-python-library.yml`
- `profile-node-service.yml`
- `profile-swift-app.yml`

Use `aviato onboard TARGET --profile PROFILE` to list the exact templates,
secrets, environments, and rulesets for a repository.

## App Store Connect

The App Store Connect workflow runs on release tags, uses macOS, and must be
called behind a protected deployment environment. Required secrets are:

- `APP_STORE_CONNECT_ISSUER_ID`
- `APP_STORE_CONNECT_KEY_ID`
- `APP_STORE_CONNECT_API_PRIVATE_KEY`
- `APPLE_CERTIFICATE_P12_BASE64`
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_PROVISIONING_PROFILE_BASE64`

The caller must provide project-specific Xcode inputs such as scheme, workspace
or project, export options plist, and version/build-number command.

## Architecture

See `ARCHITECTURE.md` for the current implementation map and
`REQUIREMENTS.md` for the broader requirements-backed system design.
