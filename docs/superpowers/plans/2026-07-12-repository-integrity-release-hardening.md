# Repository integrity and release hardening — active rollout plan

**Status:** local implementation complete; live rollout paused at an explicit
operator checkpoint.
**Updated:** 2026-07-12

This dated file is an execution aid, not the system of record. Living behavior
is owned by `docs/requirements/`, `docs/specifications/`,
`docs/architecture/`, and `docs/security/`. Current state/evidence is in
`docs/requirements/traceability.md`; unresolved work is in owning module
backlogs.

## Completed implementation

- Hardening PR #58 merged to `main` as `ca84cc8abb6c96a1eb7fd86071b2335bfb23c206`.
- Release/ref security, PR status bridging, CodeQL severity gating, scoped
  publishing, path confinement, validation, strict typing, and documentation
  corrections are implemented and covered by the repository gate.
- Release PR #42 was reopened and refreshed. Its proposal run and authoritative
  release-head dispatch passed without publishing.
- Canary PR #59 is open as a draft and intentionally contains a critical
  CodeQL finding. Ordinary CI passes while the security gate fails closed.
- Aviato's own documentation declaration is `docs: false`; the Library has no
  self-site. The opt-in consumer Zensical/Pages capability remains implemented
  and tested.

## Current live state

- **PR #60:** corrective ruleset-convergence fix, all checks green and
  independently approved, not merged.
- **Branch ruleset:** PR/check/CodeQL protection applied, but the temporary
  admin bypass is still present. This leaves SEC-007 blocked.
- **Tag ruleset:** deletion and non-fast-forward protection are active; the
  unsupported metadata-pattern rule remains a documented degraded capability.
- **PR #59:** open, blocked canary for proving CodeQL ruleset enforcement after
  convergence. Do not merge it.
- **release PR #42:** open. Do not merge or publish from it until later release
  checkpoints are explicitly authorized.
- **Dependabot:** security updates still need to be enabled and verified after
  ruleset convergence.

## Checkpoint 1 — merge the convergence fix

Blocking decision: the PR author cannot self-approve under the partially applied
one-approval rule. Explicit operator authorization is required to use the
temporary admin bypass exactly once:

```bash
gh pr merge 60 --repo amattas/aviato --merge --admin
```

Do not run that command without the user's explicit approval. Its purpose is to
land the code that removes the same bypass; it is not standing authorization for
future bypasses.

After PR #60 merges:

1. Confirm the merged SHA and required checks.
2. Reapply the `aviato-library` ruleset profile using the corrected CLI.
3. Fetch both rulesets from GitHub and record exact evidence:
   - branch `bypass_actors` is empty;
   - required contexts are the policy-bound common, security, and CI contexts;
   - CodeQL thresholds are `alerts_threshold=none` and
     `security_alerts_threshold=high_or_higher`;
   - branch/tag deletion and non-fast-forward protections remain;
   - tag metadata-pattern degradation is the only omitted rule.
4. Update SEC-007 and the security backlog from `blocked` only after the live
   response proves convergence.

## Checkpoint 2 — finish approved Phase 6 verification

After ruleset convergence:

1. Enable Dependabot automated security fixes through the GitHub API and verify
   the returned repository state.
2. Run `aviato doctor` against the Library checkout and record every healthy,
   degraded, or externally blocked result without converting warnings into
   success.
3. Use PR #59 to prove the effective branch ruleset blocks the known critical
   CodeQL alert. Link the durable PR, alert, checks, and ruleset responses in
   SEC-010 traceability.
4. Do not close or delete the canary until a separate cleanup checkpoint is
   authorized.

## Later operator checkpoints — not authorized yet

- Configure and prove a disposable consumer Pages deployment.
- Register and prove the consumer-local TestPyPI trusted publisher, then verify
  artifact identity and installation.
- Exercise disposable GHCR and App Store Connect paths required by their owning
  backlogs.
- Decide when to close/clean PR #59.
- Decide whether to merge release PR #42 and publish the release.

No local green suite substitutes for these external gates. Keep each item open
in its owning backlog until its linked evidence exists.

## Completion criteria

- SEC-007 is verified with zero live bypass actors.
- SEC-010 links the canary's effective ruleset enforcement evidence.
- Dependabot and `aviato doctor` state are recorded.
- Target-specific external backlog items are completed or explicitly retained
  as blocked.
- Release/canary cleanup occurs only at approved checkpoints.
- When no hardening rollout work remains, promote any final durable facts to
  living docs and delete this plan.
