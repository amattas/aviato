# Docs restructure + reusable docs-structure skill — design

**Date:** 2026-07-11
**Status:** approved (brainstorm 2026-07-11)

## Goal

Split the monolithic `REQUIREMENTS.md` (2,129 lines) and `ARCHITECTURE.md` (352
lines) into a per-module `docs/` tree, seed per-module backlogs from the
scattered findings documents, and ship a reusable `docs-structure` skill in the
starter kit so every other repo can adopt the same convention.

## Constraints (non-negotiable)

1. **§ integrity.** 644 docstring references in `aviato/**/*.py` (plus
   `CLAUDE.md`) cite `§N.N` section numbers. The split preserves every original
   `§`-numbered heading verbatim, never splits one `§x.y` subsection across
   files, and never renumbers. Zero code churn.
2. **Mechanical split.** Prose moves verbatim — no rewriting, no content edits
   beyond diagram conversion (below) and the minimal connective text a split
   file needs (title line + provenance note).
3. **Diagrams are Mermaid.** Fenced blocks that are *diagrams* (ASCII trees,
   flow sketches) convert to Mermaid fenced blocks. YAML/JSON/shell *examples*
   stay ordinary code fences. (~25 fences to triage: 23 in REQUIREMENTS.md,
   2 in ARCHITECTURE.md.)
4. **Falsifiable index.** A new test guards the invariant: every `§` cited in
   code must resolve through `docs/requirements/README.md` to a file that
   contains that section.

## Target tree

```
docs/
├─ requirements/
│  ├─ README.md                # § → file index + reading order
│  ├─ core/
│  │  ├─ purpose.md            # §1
│  │  ├─ principles.md         # §2 (2.1–2.14 intact)
│  │  ├─ structure.md          # §3 (3.1–3.4)
│  │  ├─ modularity.md         # §4 (4.1–4.3) + §5 preamble + §5.1
│  │  ├─ consumer-contract.md  # §6 (6.1–6.6)
│  │  ├─ state-and-failures.md # §7 + §8 (incl. 8.x list items)
│  │  ├─ definition-of-done.md # §9 + §9b
│  │  └─ backlog.md
│  └─ modules/
│     ├─ README.md             # catalog: §10 (10.1, 10.3), §15, §16, §17
│     ├─ onboarding/           # flow.md §5.2 · bootstrap.md §5.10 · backlog.md
│     ├─ scaffolding/          # sync.md §5.3 · backlog.md
│     ├─ drift/                # file-drift.md §5.5 · settings-drift.md §5.6 · backlog.md
│     ├─ reconcile/            # flow.md §5.7 · consent.md §5.8 · backlog.md
│     ├─ versioning/           # release.md §5.9 · repin.md §5.12 · backlog.md
│     ├─ fleet/                # diagnosis.md §5.4 · scan.md §5.11 · backlog.md
│     ├─ offboarding/          # flow.md §5.13 · backlog.md
│     ├─ security/             # scanning.md §5.14 · supply-chain.md §11.3 · backlog.md
│     ├─ languages/
│     │  ├─ README.md          # §12 preamble + §10.2 (language → target mapping)
│     │  ├─ python/            # requirements.md §12.1 · backlog.md
│     │  ├─ node/              # requirements.md §12.2 · backlog.md
│     │  └─ swift/             # requirements.md §12.3 · backlog.md
│     ├─ deployment/
│     │  ├─ README.md          # §11 preamble, 11.1, 11.2, 11.5–11.7 + §13 preamble + §13.5 + §14
│     │  ├─ pypi/              # requirements.md §13.1 · backlog.md
│     │  ├─ ghcr/              # requirements.md §13.2 · backlog.md
│     │  ├─ docs-site/         # requirements.md §13.3 · backlog.md
│     │  └─ apple/             # requirements.md §13.4 + §11.4 · backlog.md
│     └─ starter-kit/          # conventions.md (new; normative kit decisions) · backlog.md
├─ architecture/
│  ├─ overview.md              # Purpose, Boundaries, Non-Goals
│  ├─ infrastructure.md        # Current Components (workflows, templates, rulesets, core engine, scripts, reports)
│  ├─ data-flow.md             # Policy Source, Release Architecture (incl. ASC), Branch Protection
│  └─ validation.md            # Validation
└─ superpowers/                # unchanged (dated specs/plans stay put)
```

Notes on the awkward cases (decided, not open):

- `§10.2` moves to `languages/README.md` (it *is* the language→target mapping);
  the index maps it explicitly. `§10` preamble + `§10.1` + `§10.3` stay in
  `modules/README.md`.
- `§11.3` (privilege declaration / supply chain) lives in
  `security/supply-chain.md`; `§11.4` (ASC stored-secret confinement) lives
  with Apple. Every other `§11.x` stays together in `deployment/README.md`.
- `starter-kit/conventions.md` is the one *new* document: the kit's normative
  decisions (tag-push-only releases, digit-initiated tags, required check =
  job id `ci`, `release` environment, GitHub release last, npm hardening,
  vendored-copy model). `starter/README.md` remains the copy-paste operator
  quickstart — different audience, some overlap accepted.

## § → file index and guard test

`docs/requirements/README.md` carries a table mapping every `§`-numbered
heading to its file, plus a short reading order.

`tests/test_docs_index.py` (written first, TDD):

- Extracts every `§<num>` reference from `aviato/**/*.py` (pattern covers
  `§5.2`, `§9b`, `§8.14`, `§13.4.7`).
- Resolves each by longest-prefix walk against the index (e.g. `13.4.7` →
  `13.4` → `deployment/apple/requirements.md`), then asserts the mapped file
  contains the cited number literally.
- Asserts every index row's file exists and contains its § heading.
- Stdlib only (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` compatible).

## Root stubs and inbound references

- `REQUIREMENTS.md` and `ARCHITECTURE.md` become ~10-line pointer stubs
  (title, one-paragraph description, link to the new index) so docstring
  citations of "REQUIREMENTS §x.y" and external links keep resolving.
- Update inbound references: `CLAUDE.md` (3 mentions) and `README.md`
  (lines ~228–229).

## Backlog seeding

Sources, triaged item-by-item against current code (they date from
2026-06-09/10 — some items are already fixed):

| Source | Disposition |
|---|---|
| `FINDINGS.md` (untracked, P0–P5 + follow-up) | open items → matching module `backlog.md`; then delete locally |
| `WORKFLOW-HARDENING-PLAN.md` (tracked, C12-W1/W2/W3/W6) | open items → `versioning`/`deployment/ghcr`/`deployment/apple` backlogs; then `git rm` |
| `docs/recent-fixes.md` (tracked) | mostly done; salvage anything open, then `git rm` |

Every backlog entry records: one-line finding, severity, source doc + item id.
`OVERLAY.md` and `catalog.md` are untouched (fleet/operator artifacts, not
this repo's backlog).

## Reusable skill: `starter/skills/docs-structure/SKILL.md`

Standard agent-skills format (frontmatter `name` + `description`), generic —
no aviato-specific § numbers. Content:

1. **Canonical tree:** `docs/requirements/core/`,
   `docs/requirements/modules/<module>/<topic>.md`, `docs/architecture/`
   (`overview.md`, `infrastructure.md`, `data-flow.md`, `data-schema.md` as
   applicable). Module = cohesive capability; topics are small, single-purpose
   files; language/target families become subdirectories under their module.
2. **Backlogs:** every module directory has `backlog.md` — the *only* backlog
   location; no root-level findings monoliths.
3. **Diagrams:** all diagrams are Mermaid fenced blocks in the markdown —
   never images/binaries, never ASCII art. Code/config examples stay ordinary
   fences.
4. **Splitting monoliths code cites:** preserve section numbering verbatim,
   never split a numbered subsection across files, maintain a number→file
   index in `docs/requirements/README.md`, leave a root pointer stub.
5. **Specs/plans:** dated design docs go under `docs/superpowers/{specs,plans}`
   (or the project's equivalent) — separate from living requirements.

Distribution: copied into a consumer repo's `.claude/skills/docs-structure/`
(Claude Code) and referenced from `AGENTS.md` for other agentic coders, like
every other kit master. `starter/README.md` gains a "what to copy" line.
Installing into aviato's own `.claude/skills/` is a manual operator step
(policy-protected path).

## Execution order

1. `tests/test_docs_index.py` (red).
2. Split `REQUIREMENTS.md` → `docs/requirements/**`; build index (test green).
3. Split `ARCHITECTURE.md` → `docs/architecture/**`; Mermaid conversion in both.
4. Root stubs; update `CLAUDE.md` + `README.md`.
5. Backlog triage + seeding; retire source docs.
6. Skill + `starter/README.md` line.
7. Full gate: `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh` green; report counts.

Local commits after each major step; no push until the work is verified.

## Non-goals

- No wiring of `docs/` into `website/` (Docusaurus) or `starter/docs-site/`.
- No prose rewrites, no renumbering, no requirement changes.
- No changes to engine code beyond the new guard test.
