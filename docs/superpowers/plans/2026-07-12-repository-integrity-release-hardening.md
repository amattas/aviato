# Repository integrity and release hardening — active rollout plan

**Status:** ruleset convergence verified; live rollout continues at the next
explicit operator checkpoint.
**Updated:** 2026-07-13

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

- PR #60 merged as `a3e87ac00359309157fdeae153ebe29e03242a16` after the
  explicitly authorized one-time admin merge.
- Live branch ruleset readback proves zero bypass actors, the three exact
  required checks, exact CodeQL thresholds, and immutability.
- Live tag ruleset readback proves zero bypass actors and immutability; the
  unsupported metadata-pattern rule is the only degradation.
- **PR #59:** open, blocked canary for proving CodeQL ruleset enforcement after
  convergence. Do not merge it.
- **release PR #42:** open. Do not merge or publish from it until later release
  checkpoints are explicitly authorized.
- **Dependabot:** security updates still need to be enabled and verified after
  ruleset convergence.

## Checkpoint 1 — completed

The user explicitly authorized this one-time command, which was run once:

```bash
gh pr merge 60 --repo amattas/aviato --merge --admin
```

That authorization was consumed and is not standing authorization for any
future bypass. The hotfix CLI completed the correlated tag-rule fallback, and
the exact live readback above closed SEC-007.

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

- SEC-010 links the canary's effective ruleset enforcement evidence.
- Dependabot and `aviato doctor` state are recorded.
- Target-specific external backlog items are completed or explicitly retained
  as blocked.
- Release/canary cleanup occurs only at approved checkpoints.
- When no hardening rollout work remains, promote any final durable facts to
  living docs and delete this plan.
