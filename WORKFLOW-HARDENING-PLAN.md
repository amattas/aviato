# Deploy-Workflow Hardening Plan (C12-W1 / W2 / W3 / W6)

The 4 remaining supply-chain findings are **coordinated redesigns of the release/deploy pipeline**.
They are **operator-verified by design** (§9.2/§9.9/§13.4.7) — correctness cannot be confirmed without a
real release + credentials — so they are planned here for an implementation pass that can **test a
release**, rather than landed as unverifiable blind edits.

Already fixed & verified this cycle: **W4** (Pages build/deploy split), **W5** (Pages fail-closed
restore), **W7** (PyPI resolve gate fails closed).

---

## C12-W1 — release write-token in scope during Aviato install/derive (HIGH)

**File:** `.github/workflows/reusable-release.yml`. **Now:** one `release` job with job-wide
`contents: write` + `pull-requests: write` and `GH_TOKEN: github.token`; it installs Aviato and runs
`derive` (the largest Aviato execution, over full commit history) before any propose/tag step.
**Partial mitigation already present:** `AVIATO_REF` is pin-validated (rejects a moving branch) BEFORE
install.

**Plan (privilege-split into two jobs):**
1. `derive` job — `permissions: contents: read`, no write token. Steps: checkout (fetch-depth 0),
   setup-python, verify-ref, install Aviato, `derive` (id), `phase` (id). `outputs: next, last, release,
   phase`.
2. `release` job — `needs: derive`, `if: needs.derive.outputs.release == 'true'`,
   `permissions: contents: write, pull-requests: write`. Steps: checkout (fetch-depth 0,
   `persist-credentials: true`), setup-python, install Aviato, then the existing **propose** (`if phase
   == propose`) and **tag** (`if phase == tag`) steps verbatim, reading `NEXT`/`LAST`/`BUILD_NUMBER` from
   `needs.derive.outputs`. Workflow `outputs.released`/`outputs.tag` move to the tag step here.
3. Top-level `permissions: {}`; keep the `concurrency` group.
**Residual (document):** the write job still installs the pinned Aviato with the write token ambient
(a step can't drop perms). The split removes the token from the heavy derive phase — defense-in-depth,
not elimination. **Verify:** privilege test (union across jobs), actionlint, then a real propose→merge→
tag release on a sandbox repo.

## C12-W2 — gate validates a SHA, deploys check out a mutable tag (HIGH, TOCTOU)

**Files:** `reusable-release-gate.yml` (validates `GITHUB_SHA`) + the 4 deploys
(`reusable-pypi-publish.yml:91,220`, `reusable-docker-ghcr.yml:81`, `reusable-docs-pages.yml:94`,
`reusable-app-store-connect.yml:148`) which `checkout` `ref: ${{ inputs.release-tag || github.ref }}`,
plus the **caller** (`aviato-ci.yml` scaffold body `wf-aviato-ci.yml`) that wires gate→deploys.

**Plan (pin the gated SHA through gate→deploy):**
1. Gate emits its validated commit as an output: `outputs.gated-sha: ${{ steps.validate.outputs.sha }}`
   (set `sha=$(git rev-parse "${GITHUB_SHA}")`). It already proves tag→SHA and SHA→default-branch.
2. The caller passes `gate.outputs.gated-sha` into each deploy as a new input `gated-sha`.
3. Each deploy `checkout` uses `ref: ${{ inputs.gated-sha }}` (the immutable commit) instead of the tag,
   AND adds a pre-publish re-verify: `test "$(git rev-parse "refs/tags/${TAG}^{commit}")" = "${GATED_SHA}"`
   — fail closed if the tag was moved between gate and publish.
**Lower-risk increment if a full thread is deferred:** keep tag checkout but add the pre-publish
`tag → gated-sha` re-verify in each deploy (additive guard; needs only the gate's SHA threaded).
**Verify:** actionlint + a release where the tag is force-moved mid-run must abort the deploy.

## C12-W3 — GHCR scans one build, pushes a separate rebuild (HIGH)

**File:** `.github/workflows/reusable-docker-ghcr.yml` (the workflow itself notes non-byte-identity
≈`:203`). A mutable base image / networked Dockerfile makes the pushed digest differ from the scanned
one, so the scan does not gate what ships.

**Plan (build-once → scan-by-digest → promote):**
1. **Build once** to a local digest (no push): `docker buildx build --load` (or `--output
   type=docker,dest=image.tar`), capture the image **digest**.
2. **Scan that exact digest** (Trivy/grype) — fail closed on the policy threshold.
3. **Promote** the *same* bytes: `docker push` by digest (or `buildx ... --output type=registry` reusing
   the cached build), then tag the registry digest with the release tag/`latest` via `is_highest`. No
   second `build` between scan and push.
**Caveat:** multi-arch (buildx) builds complicate "load + scan + push the same bytes" (the `--load`
single-arch vs registry-manifest path); the implementation must pick one arch strategy and verify the
pushed `repo@sha256:` equals the scanned digest. **Verify:** a real GHCR push; assert pushed digest ==
scanned digest.

## C12-W6 — App Store submit `eval` still holds the ASC private key (MED)

**File:** `.github/workflows/reusable-app-store-connect.yml` (`SUBMIT_FOR_REVIEW_COMMAND` eval ≈`:332`).
R9-9 fixed only the version-command ordering; the free-form submit `eval` still runs with the ASC API
private key in env, so a compromised submit helper can exfiltrate it.

**Plan (remove the free-form eval from the key's blast radius):**
1. Replace the operator `eval` with a **declarative/built-in** submit (e.g. a pinned `xcrun altool`/
   Fastlane `deliver --submit-for-review` step, or App Store Connect API call) that takes a bounded
   input, not an arbitrary command.
2. If a custom submit must remain, run it in a **separate job** that receives only a short-lived
   submit-scoped token (not the raw ASC private key), mirroring the build/deploy split — the key stays in
   the job that mints the JWT, the submit job gets only what it needs.
**Verify:** an actual TestFlight/App Store submit in a sandbox app; confirm the key never enters the
free-form step's env.

---

## Cross-cutting verification for any of these
`actionlint` (syntax) + `aviato validate` (RELEASE_WORKFLOWS tag-only, action digest pins, monotonic
`is_highest` parity) + `tests/test_pipeline_privileges.py` (per-job permission union) + `shellcheck` on
`run:` blocks — then a **real release on a sandbox repo** for semantic confirmation, since none of these
are exercised by the local gate.
