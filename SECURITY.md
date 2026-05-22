# Security posture

## Supply-chain pinning (§11.3)

Third-party actions and tools invoked by any pipeline must be **pinned by 40-hex
commit digest**, never a floating tag (`@v4`) or branch. First-party GitHub
namespaces (`actions/*`, `github/*`), local composite actions (`./...`), and Aviato
reusable-workflow references (`amattas/aviato/.github/workflows/...@vX`) are exempt:
the latter is the Library version pin and follows §2.6/§6.1 (an exact `vX.Y.Z` pin
closes the delivery path; a floating `vX` is a deliberate mutable reference).

### Enforcement

- **Consumers:** `reusable-common-lint.yml` runs a *blocking* digest-pin check on
  every PR and release — a third-party `uses:` that is not a commit SHA fails the
  job. This mirrors `aviato.core.actionpins` (unit-tested) so the rule is enforced
  in CI, not merely diagnosed.
- **Tooling:** `aviato lint-actions <repo>` runs the same detector locally / in
  scripts and exits non-zero on any violation.
- **Maintenance:** `.github/dependabot.yml` tracks the `github-actions` ecosystem
  weekly, so digest pins are bumped as upstream releases are published.

### Known constraint — the Library's own bundled reusable workflows

Aviato's bundled `reusable-*.yml` invoke third-party actions (e.g. `docker/*`,
`pypa/gh-action-pypi-publish`, `aquasecurity/setup-trivy`, `maxim-lobanov/setup-xcode`)
and shell-fetched tools (`actionlint` via `curl`, `hadolint` via a container image).
These **must be digest-pinned before publish**. Resolving the correct commit SHAs /
image digests requires network access to the upstream registries; they are pinned in
the networked release/maintenance environment (and thereafter kept current by
Dependabot). Fabricating a SHA offline would break CI by referencing a non-existent
ref, so the pins are deliberately not invented here. `aviato lint-actions .` lists
exactly which references still require a digest pin.

## Credentials (§11.2 / §11.4)

OIDC-first. No stored secrets except Apple App Store Connect, which are confined
behind a protected deployment environment (§13.4). The release/deploy flow uses only
the platform `GITHUB_TOKEN`; because a token-pushed tag does not re-trigger workflow
runs and a stored PAT is forbidden, deploy runs as **in-run downstream jobs** of the
release job (propose → merge → tag → deploy in one run) rather than via a separate
tag-triggered workflow. See `reusable-release.yml`.
