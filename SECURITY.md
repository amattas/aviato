# Security policy & posture

## Reporting a vulnerability

Report vulnerabilities privately via **GitHub private vulnerability reporting** on
this repository (Security → Report a vulnerability), or by email to
`anthony@mattas.net` if the GitHub channel is unavailable. Please do not open
public issues for security reports. You should receive an acknowledgment within a
week; coordinated disclosure is appreciated.

**Scope:** the `aviato` operator CLI, the reusable workflows under
`.github/workflows/` (which execute inside *consumer* repositories' CI), the
scaffold templates the Library seeds into consumer repos, and the policy/ruleset
payloads it applies. A vulnerability in a reusable workflow affects every consumer
pinned to an affected version — please flag suspected blast radius in the report.

**Supported versions:** the latest release of each major line (consumers pin
`@X.Y.Z` or the floating major `@X`, §2.6). Fixes ship as new releases; the
floating major advances monotonically, so `@X` consumers receive fixes on their
next run after release.

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

- **Consumers:** `reusable-common-lint.yml` runs *blocking* checks on every PR and
  release by installing the pinned Aviato and running **the same single
  implementation** — `aviato lint-actions` — that operators run locally (no
  second/mirror checker exists to drift; the one-implementation rule is R9-5).
  The gate covers: mutable third-party `uses:` and unpinned images (delegated to
  a pinned **zizmor** with the bundled `aviato/library/zizmor.yml` policy),
  **workflow template injection** (zizmor `template-injection`, gated since
  2026-06), fail-closed fetch-and-execute (`curl | bash` taint analysis over a
  real shell AST), non-exact pip pins (including seeded requirements files and
  the seeded pyproject dev extras), and unsafe plain `npx` registry fetches.
- **Tooling:** `aviato lint-actions <repo>` runs the same gate locally / in
  scripts and exits non-zero on any violation; missing zizmor/bashlex fails
  closed (§5.14), never silently passes.
- **Maintenance:** `.github/dependabot.yml` tracks the `github-actions` and `pip`
  ecosystems weekly, so digest pins and exact tool pins are bumped as upstream
  releases are published.

### npm install hardening

Node and Docusaurus install paths require npm **11.10** or newer (`min-release-age`
is only honored from 11.10.0 — older 11.x silently ignores it). The reusable
workflows fail before install if npm is older, then set `ignore-scripts=true`,
`engine-strict=true`, and `min-release-age=7`. Managed Node/docs scaffolds also
write those values into `.npmrc`, and package manifests declare
`node >=24` / `npm >=11.10`, so local installs and CI use the same supply-chain
defaults. Node CI invokes local tool binaries with `npx --no-install`, and the
common lint gate rejects unsafe plain `npx`, so a missing
ESLint/Prettier/TypeScript binary fails instead of triggering a registry fetch.

### Library bootstrap local install

`local-install: true` is only for the Library bootstrapping itself before a
released reference exists. Reusable workflows require both the structural Library
anchors and `.github/aviato.yaml` with `bootstrap: true` before running
`pip install -e .`; consumer checkouts fail closed if they try to enable it.

## Credentials (§11.2 / §11.4)

OIDC-first. Two stored-secret surfaces exist, both deliberately bounded:

- **Apple App Store Connect** (six secrets), confined behind a deployment
  environment whose **required-reviewer protection is verified at run time**
  (the workflow fails closed before any secret materializes if the environment
  is unprotected). Signing and API-key material is scoped to the individual
  steps that need it; the caller-controlled version command runs before signing
  assets exist, and the optional custom submit command runs **after** signing
  cleanup with no API private key in scope (C12-W6) — the built-in declarative
  submit is the only key-bearing submission path.
- **`AVIATO_SETTINGS_TOKEN`** (optional, per consumer): an admin-capable
  **read-only-in-use** token the scheduled drift automation uses solely to READ
  protected branch settings (§5.6) — the platform token cannot. It performs no
  writes (issue updates use the ambient platform token; settings *apply* is the
  separate operator-gated §5.7 path). Omit it and settings-drift simply skips,
  fail-closed.

The release/deploy flow itself uses only the platform `GITHUB_TOKEN`; because a
token-pushed tag does not re-trigger workflow runs and a stored PAT is forbidden,
deploy runs as **in-run downstream jobs** of the release job (propose → merge →
tag → deploy in one run) rather than via a separate tag-triggered workflow.
Deploys consume the release gate's **validated commit SHA** — never the mutable
tag — and re-verify the tag against it immediately before publishing (C12-W2).
See `reusable-release.yml` / `reusable-release-gate.yml`.

## Residual, documented scopes

- The §8.15 secret guard is **type/name-based**: it blocks variables declared
  `secret: true` from the declaration and from rendered bodies; it does not
  content-inspect plain string values (a token pasted into a non-secret variable
  is within the consumer's own trust boundary).
- GHCR publishes run in a single OIDC-holding job (R7-4, accepted scope with
  in-file rationale); the scan→publish byte-identity is enforced by promoting
  the exact scanned OCI archives by digest (C12-W3).
- zizmor audits outside the gated set (`unpinned-uses`, `unpinned-images`,
  `template-injection`) are surfaced but non-gating until explicitly adopted.
