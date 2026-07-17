# Security backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [live verification] Use canary PR #59 to prove the applied ruleset blocks the critical CodeQL alert, then record the durable run/alert evidence and clean up the canary at the authorized checkpoint. — trace: SEC-010
- [live rollout] Enable Dependabot security updates and run `aviato doctor` now that ruleset convergence is verified. — trace: SEC-010
- [process] Enable repository auto-merge (`allow_auto_merge`) through the managed settings baseline so dependabot PRs converge unattended under the strict up-to-date required-checks policy (2026-07-16: eight open dependabot PRs were unmergeable individually and had to be folded into one PR, #75; each merge re-queues the next rebase+CI cycle, which auto-merge would drain without operator babysitting). Standing bypass actors and recurring admin merges stay off the table per the settled solo-maintainer liveness decision below. — source: 2026-07-16 dependabot triage · aviato/library/bundles/settings/baseline.yaml (baseline capability landed <commit>; live apply tracked by the reconcile step)
- [external watch] `pypa/gh-action-pypi-publish` is digest-pinned to a commit on the mutable `release/v1` branch (comment says `release/v1`, digest = v1.14.0, in sync as of 2026-07-16); the pin goes silently stale the next time pypa advances that branch, so recheck it on every dependency audit rather than assuming the comment. — source: 2026-07-16 dependency-matrix audit · .github/workflows/aviato-ci.yml, aviato/library/scaffold/files/wf-python-library.yml


## Settled — do not reopen

- Solo-maintainer branch liveness uses only the declaration-scoped `required_reviews: 0` exception while no independent eligible reviewer exists. Do not replace it with standing bypass actors or recurring admin merges; remove the override when another reviewer becomes eligible. — trace: SEC-007
- §11.3 detector semantics are frozen: bashlex-AST taint, fail-closed, block-level verify. NO interpreter enumeration, any-word matching, order-aware verify, grep mirrors, or a second in-workflow checker (8d069f7, accf092, faaeb10, 66951ba, 9ccea23). The same impl runs in every consumer's CI via reusable-common-lint.yml — single implementation, no mirror to drift.
- zizmor scope decision (#18): the gate covers `unpinned-uses`, `unpinned-images`, and `template-injection`; `dangerous-triggers` stays non-gating (recorded in `zizmor.yml`, `docs/security/threat-model.md`, and §11.3).
- npm/Node hardening is only ever strengthened, never relaxed (S6).
- §11.3 pin surfaces (seed dev-pins vs Library pyproject, starter digests vs root workflows, Trivy CLI input vs policy.yml, node seed devDependency parity): guards (a)-(d) implemented with validation parity checks; remaining un-automatable surface (dependabot cannot watch starter/ workflow files) is covered by the starter↔root action parity guard.
