<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

### 11.3 Privileges are declared and granted (read and deploy alike)

Every pipeline **declares** the privileges it needs; every profile that attaches
it **grants** exactly those (§8.9).

**Read / propose / report automation (Consumer-side):**

| Automation | Required job privileges | Stored secrets |
|---|---|---|
| File-drift detection (§5.5) | `contents: write`, `pull-requests: write` | none (platform token) |
| Settings-drift detection (§5.6) | settings **read** scope, `issues: write` | none (platform token) |
| Security scanning (§5.14) | `contents: read`, `security-events: write`, `actions: read` | none (platform token) |

File-drift proposes via a pull request, which requires **pushing an identity-keyed
proposal branch** — hence `contents: write`, not `contents: read` (it never mutates
the default branch directly; the PR remains the human gate). The two automations run
as **separate steps under separate tokens** (§11.2): file-drift uses the platform
token; settings-drift uses **two** tokens in distinct roles — the ambient platform token
for its tracking-issue **writes** (open/comment/revoke), and an operator-supplied admin
**read** token, scoped to the branch-protection/ruleset **reads** alone, for the reads the
platform token cannot perform. The admin token mutates nothing (read-only *in use*),
preserving the §11.2/§14 "no write-capable stored secret" posture; both are confined to that step.

**Deployment:**

| Target | Required job privileges | Stored secrets |
|---|---|---|
| PyPI | `id-token: write`, `contents: read` | none (OIDC) |
| GHCR | `packages: write`, `contents: read` | none (platform token) |
| Pages docs | `pages: write`, `id-token: write`, `contents: read` | none (platform token) |
| App Store Connect | `contents: read` | **yes** — §13.4 |

#### Pinning requirements by delivery channel

Third-party actions/tools invoked by any pipeline are **pinned to an immutable
reference**, by the strongest pin the delivery channel supports:

- GitHub Actions and container images are **commit-digest / image-digest** pinned.
- A binary fetched over the network is **checksum-verified** before execution.
- A tool installed from a package index that exposes no digest (e.g. a `pip`/`npm`
  package) is pinned to an **exact version**, never a floating latest. (Distro
  packages installed via the runner's system package manager inherit the pinned
  runner-image snapshot.)

The checker (`aviato.plugins.actionpins`, surfaced as `aviato lint-actions`) and the
in-CI gate enforce the digest-pinned classes and unsafe `npx` registry fetches;
exact-version tool pins are carried as workflow inputs (e.g. `actionlint-version`,
`yamllint-version`) or explicit exact package specs.

#### Enforcement: zizmor + fail-closed taint (one implementation)

**Enforcement is delegated + fail-closed (and runs as ONE implementation).** Action and
container-image pinning (`uses:` clauses, `container:`/`services:` images) are enforced by
**zizmor** (`unpinned-uses`/`unpinned-images`, plus `template-injection` — gated since the
2026-06 scope expansion: the audit is upstream-maintained, so gating it carries no
hand-rolled-detector flap risk) via a bundled policy config
(`aviato/library/zizmor.yml`: `actions/*`, `github/*`, and the `amattas/aviato/*` self-ref are
ref-pinnable, everything else SHA-required). zizmor is invoked
`--offline --persona=auditor --no-ignores`: offline because the gated audits are syntactic and must
not be coupled to GitHub-API availability (R10-3); auditor persona because `unpinned-images` is
silent at the default persona (R10-4); and `--no-ignores` so a consumer's inline
`# zizmor: ignore[…]` cannot waive the Library-mandated gate (R10-8).

Fetch-and-execute (`curl … | bash`) is enforced by a **fail-closed taint** rule (NOT a checksum-word
or sink allowlist — those fail open, cycle-10 R10-1/R10-2): over each command sequence (split on
`;`/`&&`/`||`/`&`), a `curl`/`wget` is a violation if its output streams into an executing
substitution or a non-pure-sink pipe target; a download to a file is **tainted**, and any later use
of a tainted file is a violation **unless a real verify *command*** (`sha256sum -c`, `cosign verify`,
`gpg --verify`, …) has cleared it. Only two shapes are clean: a pure data pipeline (`curl … | jq`)
and **download → verify → use**. **Do NOT re-introduce interpreter enumeration — it fails open and
flapped for eight commits (cycle-9 R9-1…R9-5);** the taint rule enumerates only obviously-safe data
sinks, so new executors are caught by default. The in-CI gate runs the *same* `aviato lint-actions`
(one implementation; no independent workflow-side detector), installing the pinned Aviato Library
(which carries the pinned zizmor) at the caller's `aviato-ref`.

**Scope note:** `docker run`/`docker pull`/`docker image pull`/`docker container run` of a mutable
`img:tag` inside a shell `run:` block is intentionally **not** gated (use a `container:`/`services:`
image, which zizmor pins, or pin the tag in the Dockerfile); the old shell-`docker` token checks were
dropped with the enumeration machinery (R9-4 / R10-N2).

#### npm install hardening

For npm install paths, Aviato adds an additional supply-chain guard: Node and
Node installs must run with npm **11 or newer**, because older npm rejects
the `min-release-age` option. The reusable Node and docs workflows fail closed on
npm <11 before any install command runs, set `ignore-scripts=true`, and set
`engine-strict=true` and `min-release-age=7`. Managed Node and docs scaffolds
include `.npmrc` with the same values, and package manifests declare
`node >=24` / `npm >=11`, so local project installs inherit and enforce the
posture. Node tool invocations that use `npx` must pass `--no-install` unless
they are explicitly exact-version tool fetches documented as such; the npx gate
runs inside `aviato lint-actions` (and therefore in both `aviato validate` and
the common lint workflow).

#### Day-zero exception: macOS Homebrew tools (deferred)

The Swift verify install (`brew install swift-format swiftlint`, §12.3) is **not**
version/checksum-pinned — neither tool ships a versioned Homebrew formula, and unlike
a Linux distro package a `brew install` fetches the latest formula rather than the
runner-image snapshot, so it does not cleanly fit either pinning class above. This is
a **known day-zero gap**: the Swift toolchain path is operator-verified only (§13.4.7),
and pinning these to checksum-verified release binaries is a post-day-zero hardening.
It is called out so the gap is an explicit, traceable boundary, not a silent omission.

#### Scope boundary: pipeline tooling vs. consumer project deps

This exact/digest pinning rule governs **Aviato's own pipeline supply chain** — the
actions, container images, fetched binaries, and pip/npm tools the reusable workflows
invoke (all pinned). It does **not** dictate the version ranges in a **seeded consumer
project manifest** (`pyproject.toml`'s `[project.optional-dependencies]`,
`package.json` deps): those are **seed-once, operator-owned** (§6.3) — the consumer's
own project dependencies, conventionally expressed as ranges and kept current by
Dependabot, which the operator owns and tunes after seeding. Aviato pins the *tools it
runs*, not the *consumer's project deps*.

#### First-party GitHub-owned actions exemption

**First-party GitHub-owned actions** (the `actions/*` and `github/*` namespaces —
e.g. `actions/checkout`, `actions/attest-build-provenance`, `github/codeql-action`)
are exempt from the digest requirement and pinned at **major-tag** granularity: they
share the same trust root as the runner image itself (GitHub maintains both), so a
digest pin buys no additional supply-chain isolation while costing constant churn.
**Third-party actions carry no such exemption** and are commit-digest pinned. The
checker encodes this carve-out (`actionpins._FIRST_PARTY_OWNERS`); changing it is a
deliberate policy decision, not a bug.

#### Library reference pinning: exact version vs. floating major

For the Library reference a Consumer pulls, **digest-level verifiability holds only
for exact-version pins** (`X.Y.Z`, resolved to a recorded digest / signed tag) —
those **close the supply-chain delivery path**. A **floating major pin** (`X`,
§6.1) is deliberately **mutable**: it is advanced on every release (§5.9) and may
be hand-de-advanced on rollback (§13.5), so an `X` consumer gets **tag-trust, not
content-digest immutability**. Operators who require a closed delivery path pin an
**exact version**; `X` is convenience with an explicit mutable-reference
trade-off. (The apply path is closed regardless; this is about the delivery path.)
