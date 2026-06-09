# Security posture

## Supply-chain pinning (§11.3)

Third-party actions and tools invoked by any pipeline must use the strongest pin
their delivery channel supports: GitHub Actions by 40-hex commit digest, container
images by image digest, fetched binaries by checksum, and registry tools by exact
version or local-only execution. First-party GitHub namespaces (`actions/*`,
`github/*`), local composite actions (`./...`), and Aviato reusable-workflow
references (`amattas/aviato/.github/workflows/...@X`) are exempt from the action
digest rule: the latter is the Library version pin and follows §2.6/§6.1 (an
exact `X.Y.Z` pin closes the delivery path; a floating major `X` is a deliberate
mutable reference).

### Enforcement

- **Consumers:** `reusable-common-lint.yml` runs *blocking* pin checks on every
  PR and release: mutable third-party `uses:`, unpinned Docker images,
  unchecked fetch-and-execute commands, and unsafe `npx` registry fetches fail
  the job. This mirrors `aviato.plugins.actionpins` (unit-tested) so the rule is
  enforced in CI, not merely diagnosed.
- **Tooling:** `aviato lint-actions <repo>` runs the same detector locally / in
  scripts and exits non-zero on any violation.
- **Maintenance:** `.github/dependabot.yml` tracks the `github-actions` ecosystem
  weekly, so digest pins are bumped as upstream releases are published.

### npm install hardening

Node and Docusaurus install paths require npm 11 or newer. The reusable workflows
fail before install if npm is older, then set `ignore-scripts=true`,
`engine-strict=true`, and `min-release-age=7`. Managed Node/docs scaffolds also
write those values into `.npmrc`, and package manifests declare
`node >=24` / `npm >=11`, so local installs and CI use the same supply-chain
defaults. Node CI invokes local tool binaries with `npx --no-install`, and the
common lint gate rejects unsafe plain `npx`, so a missing
ESLint/Prettier/TypeScript binary fails instead of triggering a registry fetch.

### Library bootstrap local install

`local-install: true` is only for the Library bootstrapping itself before a
released reference exists. Reusable workflows require both the structural Library
anchors and `.github/aviato.yaml` with `bootstrap: true` before running
`pip install -e .`; consumer checkouts fail closed if they try to enable it.

## Credentials (§11.2 / §11.4)

OIDC-first. No stored secrets except Apple App Store Connect, which are confined
behind a protected deployment environment (§13.4). Apple signing and App Store
Connect secrets are scoped to the individual workflow steps that need them; the
caller-controlled version command runs before signing assets are installed. The
release/deploy flow uses only the platform `GITHUB_TOKEN`; because a token-pushed
tag does not re-trigger workflow runs and a stored PAT is forbidden, deploy runs
as **in-run downstream jobs** of the release job (propose → merge → tag → deploy
in one run) rather than via a separate tag-triggered workflow. See
`reusable-release.yml`.
