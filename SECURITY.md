# Security posture

## Supply-chain pinning (§11.3)

Third-party actions and tools invoked by any pipeline must be **pinned by 40-hex
commit digest**, never a floating tag (`@v4`) or branch. First-party GitHub
namespaces (`actions/*`, `github/*`), local composite actions (`./...`), and Aviato
reusable-workflow references (`amattas/aviato/.github/workflows/...@X`) are exempt:
the latter is the Library version pin and follows §2.6/§6.1 (an exact `X.Y.Z` pin
closes the delivery path; a floating major `X` is a deliberate mutable reference).

### Enforcement

- **Consumers:** `reusable-common-lint.yml` runs a *blocking* digest-pin check on
  every PR and release — a third-party `uses:` that is not a commit SHA fails the
  job. This mirrors `aviato.plugins.actionpins` (unit-tested) so the rule is enforced
  in CI, not merely diagnosed.
- **Tooling:** `aviato lint-actions <repo>` runs the same detector locally / in
  scripts and exits non-zero on any violation.
- **Maintenance:** `.github/dependabot.yml` tracks the `github-actions` ecosystem
  weekly, so digest pins are bumped as upstream releases are published.

### npm install hardening

Node and Docusaurus install paths require npm 11 or newer. The reusable workflows
fail before install if npm is older, then set `ignore-scripts=true` and
`min-release-age=7`. Managed Node/docs scaffolds also write those values into
`.npmrc` with `engine-strict=true`, and package manifests declare
`node >=24` / `npm >=11`, so local installs and CI use the same supply-chain
defaults.

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
