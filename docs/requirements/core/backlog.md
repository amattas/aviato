# Core backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- (none)


## Settled — do not reopen

- Agnostic core: new capabilities land as data/plugins, never as core edits that name a specific target (language/registry/tool). If a change seems to need editing `aviato/core/*.py` to add a target, the abstraction is wrong (§4.3, §9b selfcheck).
- Secret rejection remains deterministic and type/name-based (§8.15). Content heuristics are intentionally out of scope: a plain variable is inside the consumer trust boundary, and heuristic token matching would create false assurance.
