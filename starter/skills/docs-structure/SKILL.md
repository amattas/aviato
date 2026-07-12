---
name: docs-structure
description: Use when creating, organizing, or splitting project documentation — requirements, specs, architecture docs, findings, or backlogs. Establishes the canonical docs/ tree (per-module requirements with per-module backlog.md, architecture docs), Mermaid-only diagrams, and numbering-preservation rules for splitting monoliths that code cites.
---

# Project docs structure

Organize long-lived project documentation in this tree. It is language- and
framework-agnostic; adapt module names to the project's domains.

```
docs/
├─ requirements/
│  ├─ README.md              # entry point; section → file index when numbering exists
│  ├─ core/                  # cross-cutting principles, contracts, definitions of done
│  └─ modules/
│     └─ <module>/           # one directory per cohesive capability
│        ├─ <topic>.md       # small, single-purpose topic files
│        └─ backlog.md       # the ONLY backlog location for this module
├─ architecture/
│  ├─ overview.md            # purpose, boundaries, non-goals
│  ├─ infrastructure.md      # components and how they're wired
│  ├─ data-flow.md           # how data moves end to end
│  └─ data-schema.md         # persistent shapes (when the project has them)
└─ superpowers/              # dated design artifacts, if the project uses that workflow
   ├─ specs/YYYY-MM-DD-<topic>-design.md
   └─ plans/YYYY-MM-DD-<feature>.md
```

## Rules

1. **Module = cohesive capability.** Topics are small, single-purpose files.
   Families (languages, deployment targets, providers) become subdirectories
   under their module (e.g. `languages/python/`), each with its own topic
   files and `backlog.md`.
2. **Backlogs live per module.** Every module directory carries `backlog.md`
   with `## Open` and `## Settled — do not reopen` sections. Never create
   root-level findings/TODO monoliths; a new finding goes straight into the
   owning module's backlog. Entry format:
   `[severity] summary — source · file:line pointer`. Settled entries record
   deliberate decisions so future reviews don't reopen them.
3. **Diagrams are Mermaid, in the markdown.** Every diagram is a ```mermaid
   fenced block — never a committed image or binary, never ASCII art. Code and
   config examples remain ordinary fenced code blocks.
4. **Splitting a monolith that code cites:** preserve section numbering
   verbatim; never split one numbered subsection across files; maintain a
   number → file index in `docs/requirements/README.md`; leave the original
   path as a short pointer stub; add a test that every number cited in code
   resolves through the index.
5. **Specs and plans are dated artifacts**, separate from living requirements.
   Requirements are updated in place; specs/plans are not rewritten to match
   later reality.
