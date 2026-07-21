# Starter documentation governance specification

Implements [REQ-DOC-001, REQ-DOC-002, and REQ-TEST-001](../../../requirements/modules/starter-kit/conventions.md).

## Distributed artifacts

| Master | Consumer path | Ownership |
|---|---|---|
| `starter/CLAUDE.md` | `CLAUDE.md` | Tool-specific wrapper plus managed governance block |
| `starter/AGENTS.md` | `AGENTS.md` | Tool-specific wrapper plus the same managed governance block |
| `starter/skills/<name>/` | `.claude/skills/<name>/` | Whole starter-managed process definition |
| `starter/docs/requirements/traceability.md` | `docs/requirements/traceability.md` | Seed-only living evidence ledger |

The managed block is bounded exactly once by
`aviato:documentation-governance:start` and
`aviato:documentation-governance:end`. Its bytes are identical in both agent
templates.

## Adoption and update behavior

1. If an agent file is absent, copy the template. If it exists without the
   markers, insert the managed block once. If the markers exist, replace only
   the bounded block and preserve all surrounding project-specific content.
2. Replace only the four recognized managed skill directories:
   `docs-structure`, `traceability`, `docs-reconciliation`, and
   `test-consolidation`. Preserve every other skill.
3. Before replacing a managed skill, compare it with the prior starter copy. A
   local modification requires an operator decision: accept the replacement or
   fork the customization under a distinct name. Never line-merge a skill.
4. Seed the traceability matrix and other living docs only when missing. Later
   updates reconcile their content; a blank starter template never overwrites
   project state.

The starter remains a reviewed copy workflow. It does not add automatic
consumer synchronization or a persistent consumer registry.

## Completion and documentation lifecycle

Before work is complete, update the requirement/specification and traceability
state, remove completed backlog entries, preserve unresolved and settled items,
and promote every durable fact out of obsolete plans. A plan may be pruned only
after links and evidence prove it contains no unique requirement, behavior,
decision, threat, mitigation, assumption, residual risk, or open work.

## Test and CI efficiency

TDD remains required for behavior changes, but every test must prove a distinct
behavior. Extend or parameterize an existing test for variants of one behavior;
do not fuse distinct behaviors into a mega-test. Suite-wide reduction uses the
`test-consolidation` skill and preserves assertions and coverage.

Verify coherently before publishing. Local commits may be batched into one
reviewable branch and pull request to avoid redundant CI runs. Cost never
weakens tests, security gates, review, release controls, evidence, or rollback
safety.

## Settled decisions — do not reopen

- Multi-arch container builds REQUIRED — amd64+arm64 native-runner matrix (G2).
- No infra/terraform profile (G3, operator decision).
- Zensical with built-in search is the sole docs baseline (operator decision 2026-07-11); prior Docusaurus and external-search decisions are historical and superseded.
- The fleet Python floor is 3.12 (operator decision 2026-07-18, made during the pydmp adoption): every fleet project targets >=3.12, and the managed lint/typecheck configs (ruff target-version py312, mypy python_version 3.12) assume it. Floor-awareness machinery (deriving config targets from a consumer's requires-python) is deliberately NOT built — revisit only if a sub-floor consumer ever needs adopting.
