# Python language backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [low] Profile asymmetry: python-component.yaml:30 adds `run-typecheck` but lacks the `typecheck-command` variable python-library.yaml:14 has, so wf-python-component.yml:35-42 never passes `typecheck-command` to reusable-python-ci.yml — a consumer needing a custom typecheck command must hand-edit. Add the variable and thread it. — FINDINGS #49 (narrowed) · aviato/library/python-component.yaml:30; wf-python-component.yml:35-42

## Settled — do not reopen

- (none)
