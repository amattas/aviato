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
^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(alpha|beta)[0-9]+)?$
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
aviato onboard amattas/example --profile python-library --pin 1.2.3 --open-pr  # adopt an existing repo via a reviewable scaffold PR
aviato provision amattas/example --profile node-service --pin 1.2.3
```

`--docs` on `onboard`/`provision` composes the opt-in docs deploy.

Fresh writes and provisioning refuse to invent a default pin. The requested pin
must already resolve to a published Aviato tag or branch; use
`--allow-unresolved-pin` only for intentional offline or test scaffolds. Already
adopted repositories keep their recorded pin during onboarding; use
`aviato repin` to move it.

Consumer lifecycle commands (see `aviato <command> --help` for the full flags):

```bash
aviato render-rulesets                       # print rendered ruleset JSON
aviato apply-rulesets OWNER/REPO --declaration /path/.github/aviato.yaml --apply  # override-aware apply: resolves checks/approvals through the consumer's declared overrides (what settings-drift remediation recommends)
aviato doctor /path/to/consumer              # classify managed artifacts + probe health
aviato sync /path/to/consumer                # materialize managed artifacts incl. caller workflows
aviato scan /path/a /path/b [--fix --audit]  # fleet diagnosis; --fix opens managed-file proposals, --audit surfaces open settings-drift tracking issues
aviato drift-report /path/to/consumer [--file-only|--settings-only] [--require-settings]  # file + settings drift report
aviato reconcile /path/to/consumer ISSUE --confirm DIFF_ID  # operator-gated settings apply, diff-bound
aviato complete-protection /path/to/consumer # idempotently (re-)apply full branch protection
aviato repin /path/to/consumer 1.3.0 [--write | --open-pr]  # move the Library version pin; --open-pr opens a reviewable re-pin proposal
aviato offboard /path/to/consumer [--write --delete-files | --open-pr]  # remove from Aviato management; --open-pr opens a reviewable removal proposal
aviato next-version --current 1.2.3 --commit "feat: x"  # derive the next SemVer from Conventional Commits
aviato bump-version 1.3.0 /path/to/consumer  # write the version into version-source locations
aviato is-highest 1.2.3 1.0.0 1.2.3          # exit 0 iff arg1 is the highest release among the rest
aviato lint-actions PATH                     # supply-chain pinning gate (zizmor + fail-closed curl|bash)
aviato validate                              # validate this repository's policy infrastructure (source checkout only)
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
- `reusable-release.yml`
- `reusable-release-gate.yml`
- `reusable-docker-ghcr.yml`
- `reusable-pypi-publish.yml`
- `reusable-docs-pages.yml`
- `reusable-app-store-connect.yml`
- `reusable-security-baseline.yml`
- `reusable-common-lint.yml`
- `reusable-consumer-automation.yml`

`reusable-release.yml` is split into a read-only derive job and a write release
job. `reusable-release-gate.yml` exports the validated commit as a `gated-sha`
output; the deploy workflows check out that exact commit — never the mutable
tag — and re-verify the tag still points at it before publishing. The GHCR
publish promotes the exact Trivy-scanned OCI archives by digest (no rebuild
between scan and push), and the PyPI/GHCR publish jobs run in GitHub deployment
environments (defaults `pypi`/`ghcr`).

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

`reusable-node-ci.yml` defaults to Node 24 and blocks npm versions below 11.10
(the floor for `min-release-age` support) before any install command. It sets
`ignore-scripts=true`, `engine-strict=true`, and `min-release-age=7`; Node
scaffolds also write those values into managed `.npmrc` files and declare
`node >=24` / `npm >=11.10` in package manifests so local and CI installs share
the same supply-chain posture. Node CI uses `npx --no-install` for local tool
bins, and the common lint gate rejects unsafe plain `npx` registry fetches.

## Profile Templates

The `templates/profile-*.yml` files compose CI, security, release validation,
and deployment jobs for common repo shapes:

- `profile-python-service.yml`
- `profile-python-library.yml`
- `profile-python-component.yml`
- `profile-node-service.yml`
- `profile-swift-app.yml`

These are **examples rendered from** the authoritative scaffold bundles
(`aviato/library/scaffold/files/wf-*.yml`); `aviato validate` fails if they drift,
and `python3 scripts/regen-templates.py` regenerates them. Prefer materializing the
real workflows with `aviato sync` / `aviato onboard --write`; committed examples
use the literal `EXAMPLE_PIN` placeholder instead of a production ref. Use
`aviato onboard TARGET --profile PROFILE` to list the exact artifacts, secrets,
rulesets, and protected deployment environments for a repository. The Python
library plan requires `pypi`, container profiles require `ghcr`, and the Swift
app plan requires `app-store-connect`; each named environment must exist with at
least one required reviewer before deployment. Zero-deploy profiles explicitly
report that none are required. The common scaffold also seeds `CONTRIBUTING.md`,
`.github/CODEOWNERS`, and issue/PR templates (seed-once; the consumer owns them
after seeding).

When `docs: true`, Aviato scaffolds a **Zensical** docs site under `website/`,
versioned onto a docs branch by a mike fork (Mermaid rendering and sitemap
generation included; search is Zensical's built-in search, no external service).
The docs publish workflow installs, versions, builds, and publishes the site
on release refs;
`docs-retention` defaults to 0, which keeps every released version's docs.

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

See `docs/architecture/` for the current implementation map and
`docs/requirements/` (§ index in `docs/requirements/README.md`) for the
requirements-backed system design.
