# Security backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [external watch] GitHub's API rejects the `tag_name_pattern` rule on this plan, so the release-tag-format ruleset applies without it and settings drift reads non-clean on that rule permanently (`aviato doctor`: `ruleset_protection_full: no`; apply-rulesets 2026-07-17 reported DEGRADED). Platform limitation (§17), not repo drift — re-check if the plan changes or GitHub ships the rule to this tier. — source: 2026-07-17 Phase-2 convergence
- [external watch] `pypa/gh-action-pypi-publish` is digest-pinned to a commit on the mutable `release/v1` branch (comment says `release/v1`, digest = v1.14.1 as of 2026-07-20); the pin goes silently stale the next time pypa advances that branch, so recheck it on every dependency audit rather than assuming the comment. First live occurrence 2026-07-20: `release/v1` had advanced to v1.14.1 while the pin sat at v1.14.0 — caught during the pydmp-pilot workflow-version sweep, exactly as predicted. — source: 2026-07-16 dependency-matrix audit · .github/workflows/aviato-ci.yml, aviato/library/scaffold/files/wf-python-library.yml


## Settled — do not reopen

- Solo-maintainer branch liveness uses only the declaration-scoped `required_reviews: 0` exception while no independent eligible reviewer exists. Do not replace it with standing bypass actors or recurring admin merges; remove the override when another reviewer becomes eligible. — trace: SEC-007
- §11.3 detector semantics are frozen: bashlex-AST taint, fail-closed, block-level verify. NO interpreter enumeration, any-word matching, order-aware verify, grep mirrors, or a second in-workflow checker (8d069f7, accf092, faaeb10, 66951ba, 9ccea23). The same impl runs in every consumer's CI via reusable-common-lint.yml — single implementation, no mirror to drift.
- zizmor scope decision (#18): the gate covers `unpinned-uses`, `unpinned-images`, and `template-injection`; `dangerous-triggers` stays non-gating (recorded in `zizmor.yml`, `docs/security/threat-model.md`, and §11.3).
- npm/Node hardening is only ever strengthened, never relaxed (S6).
- SEC-010's live proofs (canary ruleset block, Dependabot security updates, auto-merge baseline) are DONE and their durable evidence lives in the traceability SEC-010 row — do not re-run the canary or re-litigate the rollout here; completed-work detail belongs in traceability, not this backlog.
