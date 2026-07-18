# Scaffolding backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [process] python-library scaffold seeds no package/tests skeleton, so a FRESH repo's first CI is red (mypy --strict: no .py files) until the operator adds code — seed a minimal package+test skeleton or document the red-until-code expectation. — source: 2026-07-18 §13.3 live proof
- [external verification] The 2026-07-16 seed refresh moved the node devDependency majors (eslint/@eslint/js ^10, eslint-plugin-security ^4, vitest/@vitest/coverage-v8 ^4, typescript ^7 — the native compiler); the seeded flat `eslint.config.mjs` and tsconfig were verified compatible on paper only. On the first fresh node scaffold, run `npm install && npm run lint && npm run typecheck && npm test` to prove the seeded config actually works on the new majors. — source: 2026-07-16 dependency-matrix audit · aviato/library/scaffold/files/package.json.ts.txt


## Settled — do not reopen

- Templates are only ever regenerated via `scripts/regen-templates.py`; never hand-edited. `aviato validate` fails on template/scaffold parity drift.
- Swift/Xcode project and package manifests remain operator-owned and are not seeded (§12.3); the earlier backlog request for a Swift manifest fragment contradicted that settled contract and is closed as a non-defect.
