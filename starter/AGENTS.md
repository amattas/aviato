# Project guidance for Codex and other agentic coders

Keep project-specific commands, architecture notes, and constraints outside the
managed block below. Starter updates replace only that block.

<!-- aviato:documentation-governance:start -->
## Documentation governance

Use the repo-local skills under `.claude/skills/` when their trigger applies:

- `docs-structure` for requirements, specifications, architecture, security docs, backlogs, traceability, and documentation organization.
- `traceability` when creating or updating `docs/requirements/traceability.md` or changing requirement/threat state.
- `docs-reconciliation` before pruning plans, findings, stale docs, or completed backlog work.
- `test-consolidation` for suite-wide test cleanup or redundant-test reduction.

Requirements are the living record of what and why; specifications own precise
testable behavior; architecture owns current structure; `docs/security/` owns
threats and controls. Superpowers specs and plans are temporary delivery
artifacts, not the system of record.

Before declaring feature or documentation work complete:

1. Close the tracking issues (label `backlog`) for completed work; file unresolved work as GitHub issues labeled `backlog`; record deliberate settled decisions in the owning module page's `Settled decisions — do not reopen` section.
2. Update `docs/requirements/traceability.md` with the actual requirement/threat state and existing implementation and verification evidence.
3. Promote durable requirements, behavior, decisions, threats, mitigations, assumptions, and residual risks out of old plans before pruning them.
4. Never claim an external gate passed without durable evidence.

## Tests and cost efficiency

TDD rigor does not mean excessive test volume. Do not add trivial, redundant,
or near-duplicate tests. Before adding a test, inspect the existing suite and
extend or parameterize an existing test when cases exercise one behavior. Use
the framework's native parameterized tests; never merge distinct behaviors into
a mega-test. Every test must assert behavior not already proved elsewhere.

Correctness on the first pass avoids token-expensive rework. Verify locally
before publishing. Each push, pull request update, and merge may trigger CI and
consume GitHub resources, so batch coherent, reviewable changes into one branch
and PR when safe. Do not push local checkpoints merely for storage. Cost never
justifies skipping required tests, security gates, review, release controls, or
evidence. Keep unrelated or high-risk changes separate when reviewability or
rollback safety requires it.
<!-- aviato:documentation-governance:end -->
