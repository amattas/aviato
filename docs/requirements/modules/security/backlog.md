# Security backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [external watch] GitHub's API rejects the `tag_name_pattern` rule on this plan, so the release-tag-format ruleset applies without it and settings drift reads non-clean on that rule permanently (`aviato doctor`: `ruleset_protection_full: no`; apply-rulesets 2026-07-17 reported DEGRADED). Platform limitation (§17), not repo drift — re-check if the plan changes or GitHub ships the rule to this tier. — source: 2026-07-17 Phase-2 convergence
- [external watch] `pypa/gh-action-pypi-publish` is digest-pinned to a commit on the mutable `release/v1` branch (comment says `release/v1`, digest = v1.14.0, in sync as of 2026-07-16); the pin goes silently stale the next time pypa advances that branch, so recheck it on every dependency audit rather than assuming the comment. — source: 2026-07-16 dependency-matrix audit · .github/workflows/aviato-ci.yml, aviato/library/scaffold/files/wf-python-library.yml


## Settled — do not reopen

- Solo-maintainer branch liveness uses only the declaration-scoped `required_reviews: 0` exception while no independent eligible reviewer exists. Do not replace it with standing bypass actors or recurring admin merges; remove the override when another reviewer becomes eligible. — trace: SEC-007
- §11.3 detector semantics are frozen: bashlex-AST taint, fail-closed, block-level verify. NO interpreter enumeration, any-word matching, order-aware verify, grep mirrors, or a second in-workflow checker (8d069f7, accf092, faaeb10, 66951ba, 9ccea23). The same impl runs in every consumer's CI via reusable-common-lint.yml — single implementation, no mirror to drift.
- zizmor scope decision (#18): the gate covers `unpinned-uses`, `unpinned-images`, and `template-injection`; `dangerous-triggers` stays non-gating (recorded in `zizmor.yml`, `docs/security/threat-model.md`, and §11.3).
- npm/Node hardening is only ever strengthened, never relaxed (S6).
- §11.3 pin surfaces (seed dev-pins vs Library pyproject, starter digests vs root workflows, Trivy CLI input vs policy.yml, node seed devDependency parity): guards (a)-(d) implemented with validation parity checks; remaining un-automatable surface (dependabot cannot watch starter/ workflow files) is covered by the starter↔root action parity guard.
- SEC-010 canary ruleset proof: verified live 2026-07-17 and recorded in the traceability SEC-010 row (canary PR #59 BLOCKED-while-MERGEABLE with only security gates failing, code_scanning rule id 17482301, critical alert #23); canary closed and branch deleted at the authorized checkpoint. Do not re-run — the evidence links are durable.
- Dependabot security updates: enabled 2026-07-17 via the §5.7 reconcile flow (tracking issue #81, diff d7c86120, human consent label), verified live (`security_and_analysis.dependabot_security_updates: enabled`) and by `aviato doctor` (`dependabot_security_updates: yes`). — trace: SEC-010
- Repository auto-merge: baseline capability landed d1d8654 (0.4.x); applied live 2026-07-17 through the same consented reconcile (issue #81) — `allow_auto_merge: true` verified on the repo. Dependabot PRs now converge unattended under the strict up-to-date policy; the solo-maintainer liveness decision above still governs (no bypass actors, no admin merges).
