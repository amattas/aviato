# Scaffolding backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [low] Seeded LICENSE ships literal `{{ owner }}` — only `year` is derived (onboarding.py:65), so every consumer gets a meaningless copyright line. Derive `owner` like `year`. — FINDINGS #28 · aviato/library/scaffold/files/license.txt:3; core/onboarding.py:65
- [low] Shared scaffold constants are duplicated by hand with no parity guard: cron `23 5 * * 1` across wf-python-library/service/component.yml + wf-swift-app/node-service.yml, the pydoc-markdown pin ×2, python-version ×3-4. Hoist to render vars or add a validation parity check. — FINDINGS #43 · aviato/library/scaffold/files/wf-*.yml
- [med] ⚖ §12 common-scaffold artifacts are still incomplete: the swift package-manifest fragment from the resolved decision was never added (only the python test+coverage pyproject landed); common.yaml has no reference to a swift-package/swift-manifest template. Decision (2026-06-09): add ALL §12-promised artifacts (CONTRIBUTING, CODEOWNERS, issue/PR templates, python test+coverage config, swift package-manifest fragment) as seed-once templates. — FINDINGS #48 (narrowed) · aviato/library/bundles/scaffold/common.yaml

## Settled — do not reopen

- Templates are only ever regenerated via `scripts/regen-templates.py`; never hand-edited. `aviato validate` fails on template/scaffold parity drift.
