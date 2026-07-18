# Scaffolding backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [process] Managed `.gitignore` overwrites the consumer's file wholesale, leaving no legitimate home for SHARED, ROOT-scoped, project-specific ignore patterns (nested .gitignore files cannot scope to root; .git/info/exclude is not shared with collaborators; hand-edits to the managed file are perpetually drift-flagged and revert-prone). Design a managed-BLOCK mode: a marker-delimited region aviato owns and drift-checks inside an otherwise operator-owned file, reusing the existing §6.2 marker machinery — then reclassify gitignore-common to it. Surfaced planning the pydmp adoption (first fleet consumer with a pre-existing root .gitignore). — source: 2026-07-18 pydmp onboarding review · aviato/library/scaffold/gitignore-common.yaml
- [process] check_output_collisions compares UNRENDERED output_path strings; two different templates could render to the same concrete path (scaffold overlay then silently last-write-wins instead of the intended §4.2 hard error). Dormant today (one templated output exists); render-aware collision detection needed before more templated outputs land. — source: 2026-07-18 Task-C review · aviato/core/onboarding.py:109-124
- [external verification] The 2026-07-16 seed refresh moved the node devDependency majors (eslint/@eslint/js ^10, eslint-plugin-security ^4, vitest/@vitest/coverage-v8 ^4, typescript ^7 — the native compiler); the seeded flat `eslint.config.mjs` and tsconfig were verified compatible on paper only. On the first fresh node scaffold, run `npm install && npm run lint && npm run typecheck && npm test` to prove the seeded config actually works on the new majors. — source: 2026-07-16 dependency-matrix audit · aviato/library/scaffold/files/package.json.ts.txt


## Settled — do not reopen

- Templates are only ever regenerated via `scripts/regen-templates.py`; never hand-edited. `aviato validate` fails on template/scaffold parity drift.
- Swift/Xcode project and package manifests remain operator-owned and are not seeded (§12.3); the earlier backlog request for a Swift manifest fragment contradicted that settled contract and is closed as a non-defect.
