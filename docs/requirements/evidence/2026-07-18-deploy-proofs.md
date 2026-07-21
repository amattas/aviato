# 2026-07-18 Phase-3 deploy-pipeline live-proof evidence

Condensed record of the four external-verification proofs closed this phase: §13.1
(TestPyPI), §13.2 (GHCR), §13.3 (docs-site Pages), and §13.5 (rollback/yank). Full
session evidence lived in disposable proof repos (`amattas/aviato-proof-docs`,
`amattas/aviato-proof-ghcr`) that are deleted after this record lands — every fact
below is captured inline (dates, versions, digests, run outcomes), not as a link to
those repos. Links to `amattas/aviato` PRs/releases are durable and kept as links.

Owning modules (settled decisions): [PyPI](../../specifications/modules/deployment/pypi/requirements.md) ·
[GHCR](../../specifications/modules/deployment/ghcr/requirements.md) ·
[docs-site](../../specifications/modules/deployment/docs-site/requirements.md) ·
[deployment](../modules/deployment/README.md) ·
[scaffolding](../../specifications/modules/scaffolding/sync.md) ·
[reconcile](../../specifications/modules/reconcile/consent.md).
Open follow-ups from this phase are tracked as [GitHub issues labeled `backlog`](https://github.com/amattas/aviato/issues?q=is%3Aissue+label%3Abacklog).
Traceability rows: [§13.1, §13.2, §13.3, §13.5](../traceability.md).

## §13.1 — TestPyPI (PROVEN)

Published `aviato` 0.4.1a2 to TestPyPI 2026-07-17 through the consumer-local OIDC
trusted publisher (environment `pypi`, required reviewer gate).

| DoD item | Result |
|---|---|
| Trusted-publisher OIDC identity | PASS — environment-scoped publish succeeded, no long-lived token |
| PEP 691 confirmation | PASS — green |
| pip-download from the test index | PASS — verified installable |
| Provenance attestation | PASS — `gh attestation verify` exit 0 |
| Real-PyPI half | Already satisfied — production releases 0.3.0/0.4.0/0.4.1 |

The redirect variable `PYPI_REPOSITORY_URL` was set environment-scoped for the proof
and **removed after**. TestPyPI yank of `0.4.1a2` executed by the operator 2026-07-18
(§11.6 hygiene) — not a code gap, no automation path exists for it by design.

## §13.2 — GHCR (PROVEN, single-arch)

Ran on `amattas/aviato-proof-ghcr` (disposable, public, profile `python-service`).
Blocked twice before completing: first by the private-repo/no-GHAS code-scanning
403 (resolved when the repo was flipped public), then by a genuine Trivy v0.72.0
regression (see Finding 4 below, fixed mid-proof in aviato 0.4.1). Three releases
(0.1.2, 0.2.0, hand-tagged 0.1.3) exercised the full pipeline post-fix.

| DoD item | Result |
|---|---|
| Per-arch build→scan→push byte identity (C12-W3) | PASS (single-arch) — 3 runs, each `<plat>: scanned digest <sha> pushed byte-identical.` |
| Trivy v0.72 SARIF + HIGH/CRITICAL gate | PASS — `trivy image --input "oci/${slug}.layout"` (0.4.1 fix) clean (0 vulns) on all 3 runs |
| SBOM artifact `aviato-image-sboms` | PASS — present on all 3 runs (e.g. 11,459 bytes on the 0.2.0 run) |
| Provenance attestation verifies | PASS — `gh attestation verify oci://ghcr.io/amattas/aviato-proof-ghcr:0.1.2\|0.2.0 --owner amattas` exit 0; builder id names `reusable-docker-ghcr.yml@refs/tags/0.4.1` |
| Manifest references only scanned digests | PASS — no "does not reference scanned digest" error on any of the 3 runs |
| Monotonic alias across releases | PASS — 0.2.0 (higher) moved `latest` off 0.1.2's digest; hand-pushed 0.1.3 (old line, lower) computed `is_highest=false`, the "Tag and push latest" step **skipped**, `latest` unchanged (both confirmed via the GHCR package API) |

**Known limitation (new open item, not a mission failure):** true multi-arch
(>1 platform in one release) is not currently provable on aviato 0.4.1 — a second,
distinct upstream defect (Finding 6 below) blocks it. Filed as a new GHCR backlog
Open item.

## §13.3 — docs-site Pages (PROVEN)

Ran on `amattas/aviato-proof-docs` (disposable, public, profile `python-library`,
`docs: true`). Sequence of releases 0.1.0 → 0.1.1 → 0.1.2 → 0.2.0, each merged,
tagged, and deployed; a hand-tagged `0.1.3` on the old `0.1.2` commit exercised the
monotonic-guard-holds direction.

| DoD item | Result |
|---|---|
| 0. Diagnose + fix initial scaffold CI failure | PASS — fixed via a package/tests skeleton PR (see Finding 5) |
| 1. Drive releases through the tag pipeline incl. docs deploy | PASS — 0.1.0/0.1.1/0.1.2/0.2.0, each merged + tagged + deployed |
| 2. Docs BRANCH DoD (version dir + `latest` alias) via `gh-pages` alone | PASS — `versions.json` consistent, `latest` a git symlink to the correct version dir |
| 3. SERVED site (latest resolves, search index, Mermaid, sitemap.xml) | PASS from release 0.1.2 onward, after fixing two real bugs (Findings 1 and — a Pages-artifact name collision, fixed consumer-side) |
| 4. Monotonic proof (minor moves `latest`; old-line patch doesn't) | PASS — minor move fully live; old-line non-move proven via the exact policy function (`aviato is-highest`, parity-checked against the live inline guard) plus two live, correctly-behaving gates on the actual old commit (the docs job itself is architecturally unreachable from a tag-context run — a real, documented pipeline property, not a proof gap) |

`versions.json` progression confirmed: `0.1.0` → adds `0.1.1` → adds `0.1.2`
(`latest` alias) → adds `0.2.0` (`latest` alias moves). Served URLs all 200: root
redirect, `/latest/`, `/0.2.0/`, `/0.2.0/sitemap.xml`, `/0.2.0/search.json`, Mermaid
bundle present in the page JS.

## §13.5 — rollback/yank (executed/documented 2026-07-18)

All four deployment legs closed:

- **GHCR** — live rollback demonstrated on `amattas/aviato-proof-ghcr`'s package:
  deleted the bad-release manifest + per-arch + attestation versions (ids
  `1043483021`/`1043482962`/`1043483186`/`1043483171`); registry rolled back to
  `0.1.2`/`0.1.3` with `latest` removed alongside the bad manifest. Re-point
  mechanism confirmed: pipeline re-run on the old tag, or `skopeo copy`.
- **Floating-major tag** — hand-de-advanced tag `0` from the bad release's commit
  `076a0875` back to the prior good commit `03236f13`, proving the §13.5
  hand-de-advance mechanism live.
- **PyPI** — the §13.1 TestPyPI yank of `0.4.1a2`, executed by the operator 2026-07-18 (UI; PyPI exposes no yank API). All four §13.5 legs are now executed or mechanism-documented.
- **Docs-site** — the `gh-pages` branch is a plain git-revertable ref (documented
  mechanism); no live demo needed, same conclusion as the branch-state proof in
  §13.3.

## Six Library findings discovered by these proofs

1. **`git archive` cwd-relative pathspec bug** (`reusable-docs-pages.yml`,
   "Materialize exact docs branch tree" step) — run under the job's docs
   working-directory, `git archive <ref>` with no explicit pathspec implicitly
   scopes to that subdirectory *within the target tree*; the `gh-pages` branch has
   no such subdirectory (flat layout), so the archive silently comes back empty —
   every job reports green while the served Pages site 404s. **Fixed in
   [PR #85](https://github.com/amattas/aviato/pull/85)** (`git archive` now runs
   from the repository root).
2. **Actions "create and approve pull requests" permission is off by default and
   unmodeled** — breaks `release / Cut release`'s PR-creation step on every fresh
   repo (`GraphQL: GitHub Actions is not permitted to create or approve pull
   requests`); worked around in both proofs by the operator opening the release
   PR directly against the bot-pushed branch. **Not fixed — filed as a new
   [open backlog issue](https://github.com/amattas/aviato/issues?q=is%3Aissue+label%3Abacklog) (onboarding).**
3. **Classic branch-protection reconciliation gap** — `complete-protection`/
   `apply-rulesets --apply` correctly update a matching ruleset's
   `required_reviews` override but silently no-op a pre-existing, separately
   configured *classic* branch-protection review count that outranks it; GitHub
   enforces the strictest of the two, so the PR stayed blocked until patched
   directly (`PATCH .../protection/required_pull_request_reviews`). **Not fixed —
   filed as a new [open backlog issue](https://github.com/amattas/aviato/issues?q=is%3Aissue+label%3Abacklog) (reconcile).**
4. **Trivy v0.72.0 cannot open a buildx `type=oci` tarball** —
   `reusable-docker-ghcr.yml` built with `--output type=oci,dest=oci/${slug}.tar`
   and passed the bare tar path to `trivy image --input`; Trivy 0.72.0's
   `dockers_v2` migration broke that auto-detection (`unable to open ... as a
   Docker image` / `as an OCI Image`), hard-blocking the GHCR publish gate for
   every consumer on the 0.4.0 pin. **Fixed in
   [PR #85](https://github.com/amattas/aviato/pull/85)** (extract the OCI archive
   to an unpacked layout directory before scanning).
5. **`python-library` scaffold seeds no package/tests skeleton** — a fresh repo's
   first CI run is red (`mypy --strict: no .py files`, `pytest` exit 5, no tests
   collected) until the operator adds source; also found a related onboarding
   substitution gap (`website/zensical.toml`'s `{{ project-name }}`/`{{ repo }}`
   placeholders left unsubstituted). **Not fixed — filed as a new
   [open backlog issue](https://github.com/amattas/aviato/issues?q=is%3Aissue+label%3Abacklog) (scaffolding).** The
   prerelease/dev-suffixed version handling this proof also exercised
   (`aviato` carrying a §11.6 dev-suffixed version for the alpha stage) **was
   fixed in [PR #84](https://github.com/amattas/aviato/pull/84)**; a related PEP
   691 confirm-filter bug was fixed in
   [PR #80](https://github.com/amattas/aviato/pull/80).
6. **Multi-arch SARIF-category collision** — the per-platform Trivy scan loop in
   `reusable-docker-ghcr.yml` writes every platform's SARIF into the same
   directory with no distinguishing `category`, and
   `github/codeql-action/upload-sarif@v4` rejects multiple same-category SARIF
   runs under GitHub's 2025-07-21 policy change (`.github/workflows/aviato-ci.yml:docker`
   auto category collides across platforms). Both platforms built, extracted, and
   scanned clean before the upload step failed — the build/scan/digest machinery
   itself is multi-arch-correct; only the SARIF upload needs a per-platform
   `category`. **Not fixed — filed as a new
   [open backlog issue](https://github.com/amattas/aviato/issues?q=is%3Aissue+label%3Abacklog) (GHCR)**, noted as
   blocking the container-fleet migration's G2 (arm64) phase.

Also landed this phase, discovered while repinning the proof repos through the
CLI rather than by the deploy pipelines themselves: **`aviato repin`'s Library
tarball download used a nonexistent `gh api --output` flag** — fixed in
[PR #86](https://github.com/amattas/aviato/pull/86) (stream the tarball via
stdout instead).

## §11.6 cleanup state

- TestPyPI yank of `aviato` 0.4.1a2: **done** (operator UI, 2026-07-18; PyPI exposes no yank API by design).
- Proof repos `amattas/aviato-proof-docs` and `amattas/aviato-proof-ghcr`: **deleted
  after this record lands** — nothing in this file depends on them remaining
  reachable.
