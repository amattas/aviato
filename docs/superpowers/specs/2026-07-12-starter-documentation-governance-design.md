# Starter documentation governance — design

**Date:** 2026-07-12  
**Status:** approved (brainstorm 2026-07-12)

## Goal

Extend the vendored starter kit with a small, tool-neutral documentation
governance pack. Every consumer receives compatible instructions for Claude
Code and Codex, a canonical traceability matrix, and repo-local skills that
keep requirements, specifications, architecture, security documentation, and
backlogs accurate without treating dated Superpowers artifacts as permanent
project records.

## Distribution and compatibility

The starter kit gains `starter/CLAUDE.md` and `starter/AGENTS.md`, copied to
the consumer repository root as `CLAUDE.md` and `AGENTS.md`.
`AGENTS.md` is the Codex template because it is the recognized repository
instruction filename. Both files express the same governance policy and direct
agents to the canonical skills copied under `.claude/skills/`:

- `docs-structure`
- `traceability`
- `docs-reconciliation`

Keeping one skill copy avoids drift between tool-specific directories. Claude
Code discovers the skills in its conventional location; `AGENTS.md` instructs
Codex and other agents to read the same files explicitly. The starter README
lists the exact source and destination paths for all templates. The canonical
skill masters remain under `starter/skills/<name>/` and are copied to
`.claude/skills/<name>/` in the consumer. The matrix master is
`starter/docs/requirements/traceability.md` and is copied to the matching
consumer path.

## Canonical living documentation

The docs-structure skill defines these ownership boundaries:

```text
docs/
├─ requirements/
│  ├─ README.md
│  ├─ traceability.md
│  ├─ core/
│  └─ modules/<module>/
├─ specifications/
│  ├─ README.md
│  ├─ core/
│  └─ modules/<module>/
├─ architecture/
│  ├─ overview.md
│  ├─ infrastructure.md
│  ├─ data-flow.md
│  ├─ data-schema.md
│  └─ security.md
├─ security/
│  ├─ threat-model.md
│  └─ controls.md
└─ superpowers/
   ├─ specs/
   └─ plans/
```

Requirements define what must be true and why: stable IDs, scope,
constraints, acceptance criteria, and stakeholder-visible outcomes.
Specifications define precise, testable behavior: interfaces, workflows,
state transitions, schemas, error behavior, compatibility rules, and edge
cases. Architecture describes the current structural solution and its
dependencies. Backlogs contain unresolved work and explicitly settled
decisions only.

Security is cross-cutting. Security requirements use stable `SEC-*` IDs;
threats use stable `THREAT-*` IDs. The threat model records assets, actors,
entry points, trust boundaries, abuse cases, mitigations, assumptions, and
accepted residual risks. The controls inventory records implemented controls
and their operational assumptions. The architecture security view shows where
those controls sit in the component and data-flow architecture.

Files under `docs/superpowers/` are dated design and execution artifacts. They
support delivery but are not the system of record. Durable decisions,
requirements, behavioral details, threats, mitigations, and structural facts
must be promoted into the living documentation.

## Traceability matrix

Every consumer receives `docs/requirements/traceability.md`. It contains one
canonical table with these fields:

| Field | Purpose |
|---|---|
| ID | Stable requirement or threat identifier |
| Source | Owning requirement or threat-model link |
| State | `proposed`, `accepted`, `implemented`, `verified`, `blocked`, or `retired` |
| Specification | Link to the precise behavioral contract, when applicable |
| Implementation evidence | Links to code, configuration, migrations, or immutable change evidence |
| Verification evidence | Links to tests, checks, reports, or clearly named external gates |
| Notes | Short rationale, blocker, residual risk, or retirement explanation |

The intended chain is:

`THREAT-* -> SEC-* requirement -> specification -> control/code -> verification`

Non-security requirements use the same chain beginning at their requirement
ID. A row may not advance to `implemented` without implementation evidence or
to `verified` without verification evidence. The matrix must not invent
evidence, and external verification that has not occurred remains explicitly
blocked or outstanding.

## Skill responsibilities

### `docs-structure`

Defines the canonical tree, the requirements/specifications distinction,
per-module backlogs, Mermaid-only diagrams, numbering preservation when
splitting cited documents, security document ownership, and the temporary
status of dated Superpowers artifacts.

### `traceability`

Creates or maintains the canonical matrix. It discovers stable requirement and
threat IDs, verifies that source and evidence links resolve, detects duplicate
or missing IDs, validates state transitions, and reports contradictions
between documentation and repository evidence. It updates rows conservatively
and never marks work complete from prose claims alone.

### `docs-reconciliation`

Runs an ordered cleanup:

1. Inventory living docs, module backlogs, and dated design artifacts.
2. Identify durable decisions, constraints, behavior, threats, mitigations,
   assumptions, acceptance criteria, and unresolved work.
3. Promote each durable fact into its owning requirement, specification,
   architecture, security, or settled-decision document.
4. Update and validate traceability.
5. Remove completed entries from backlog `Open` sections.
6. Prune obsolete plans and design specs only after promotion is verified.
7. Keep unresolved work in the owning module backlog.

A security artifact cannot be pruned until every durable threat, mitigation,
assumption, and accepted risk has a living home and traceability link.

## Agent instructions and cost efficiency

Both agent templates require agents to use the three skills when relevant and
to reconcile the backlog and traceability matrix before declaring feature or
documentation work complete. They also establish these cost principles:

- Correctness on the first pass is usually cheaper than rework; understand the
  source of truth and verify locally before publishing changes.
- Each branch push, pull request update, and merge can trigger paid or
  token-consuming CI. Batch coherent, reviewable work into one branch and pull
  request when that reduces redundant runs.
- Do not push checkpoint commits merely to preserve work that is already safe
  locally. Prefer local commits until the coherent change is ready for review.
- Cost never justifies skipping required tests, security gates, review,
  release controls, or evidence collection.
- Separate unrelated or high-risk changes even when combining them would be
  cheaper; reviewability and rollback safety remain requirements.

## Validation

Tests are written before the templates and assert:

1. Both root agent templates, all three skills, and the traceability template
   exist in the starter master.
2. Every path referenced by an agent template or the starter README resolves
   within the copied starter layout.
3. `CLAUDE.md` and `AGENTS.md` contain equivalent governance, completion, and
   cost-efficiency requirements while retaining tool-specific introductions.
4. The traceability template contains the required fields and allowed states.
5. The skills use the canonical paths and distinguish requirements,
   specifications, architecture, security, backlogs, and temporary artifacts.
6. No template contains unresolved project-specific placeholders. Optional
   documents are clearly labeled instead of represented by placeholder text.

The full repository validation gate must pass before the branch is published.

## Non-goals

- Automatically inferring that work is complete without repository evidence.
- Treating Git history, pull requests, or Superpowers plans as the only system
  of record for requirements or project state.
- Duplicating skill bodies across agent-specific directories.
- Adding a hosted documentation database or external traceability service.
- Weakening verification or review to reduce CI usage.
