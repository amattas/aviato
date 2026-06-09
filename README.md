<p align="center">
  <img src="docs/assets/aviato.jpg" alt="Aviato — Where code takes flight" width="520">
</p>

# Aviato

Aviato is a reusable GitHub policy, CI, release, and onboarding conventions
library. It centralizes shared workflows, rulesets, and operator tooling without
keeping a committed inventory of consumer repositories.

## Policy

`aviato/library/policy.yml` is the canonical source for policy constants (it lives
inside the package so it ships in the wheel for installed ruleset rendering).

Release tags must match:

```text
^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta)[0-9]+)?$
```

Accepted examples: `1.2.3`, `1.2.3-alpha1`, `1.2.3-beta2`.

Rejected examples: `v1.2.3` (no `v` prefix allowed), `1.2.3-beta.1`,
`build-20260519.0215`.

Release publishing is tag-only. Legacy `release/*` branches should be cleaned up
in consumer repositories rather than supported by release publish workflows.

## What Is Here

- `aviato/library/policy.yml` - canonical policy constants (packaged; ships in the wheel).
- `aviato/library/rulesets.yml` - ruleset manifest.
- `aviato/library/rulesets/*.json` - GitHub ruleset templates.
- `.github/workflows/reusable-*.yml` - reusable CI, release, deploy, and security workflows.
- `templates/profile-*.yml`, `templates/consumer-automation.yml` - composed, copyable
  caller-workflow examples for consumer repos (rendered from the scaffold bundles; they
  include the always-on security baseline, §2.13). Use these composed callers rather than
  hand-wiring a single reusable workflow, which can omit the required baseline.
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

Onboard or provision consumers with an explicit published Library pin:

```bash
aviato onboard /path/to/repo --profile python-library --pin 1.2.3 --write
aviato provision amattas/example --profile node-service --pin 1.2.3
```

Fresh writes and provisioning refuse to invent a default pin. The requested pin
must already resolve to a published Aviato tag or branch; use
`--allow-unresolved-pin` only for intentional offline or test scaffolds. Already
adopted repositories keep their recorded pin during onboarding; use
`aviato repin` to move it.

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

`reusable-node-ci.yml` and the Docusaurus Pages workflow default to Node 24 and
block npm versions below 11 before any install command. They set
`ignore-scripts=true` and `min-release-age=7`; Node and docs scaffolds also
write those values plus `engine-strict=true` into managed `.npmrc` files and
declare `node >=24` / `npm >=11` in package manifests so local and CI installs
share the same supply-chain posture.

## Profile Templates

The `templates/profile-*.yml` files compose CI, security, release validation,
and deployment jobs for common repo shapes:

- `profile-python-service.yml`
- `profile-python-library.yml`
- `profile-node-service.yml`
- `profile-swift-app.yml`

These are **examples rendered from** the authoritative scaffold bundles
(`aviato/library/scaffold/files/wf-*.yml`); `aviato validate` fails if they drift,
and `python3 scripts/regen-templates.py` regenerates them. Prefer materializing the
real workflows with `aviato sync` / `aviato onboard --write`; committed examples
use the literal `EXAMPLE_PIN` placeholder instead of a production ref. Use
`aviato onboard TARGET --profile PROFILE` to list the exact artifacts, secrets,
environments, and rulesets for a repository.

When `docs: true`, Aviato scaffolds a Docusaurus site under `website/` with the
first-party Docusaurus ESLint plugin, Algolia search theme, Mermaid rendering,
and sitemap configuration through the classic preset. The docs publish workflow
installs, lints, versions, builds, and publishes the site on release refs.

The Library's own `.github/aviato.yaml` uses the internal `aviato-library`
profile and `bootstrap: true`. `local-install: true` is valid only for this
structural Library bootstrap path; reusable workflows fail before
`pip install -e .` if a consumer tries to enable it.

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

Apple/App Store Connect credentials are scoped to the specific workflow steps
that need them. The caller-controlled version command runs before signing assets
are installed, so Apple secrets are not exposed to arbitrary versioning logic.

## Architecture

See `ARCHITECTURE.md` for the current implementation map and
`REQUIREMENTS.md` for the broader requirements-backed system design.
