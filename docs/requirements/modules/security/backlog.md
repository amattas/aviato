# Security backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [med] `persist-credentials: false` is still missing on two non-pushing checkouts (all others fixed): reusable-consumer-automation.yml:73 has no `with:` clause at all (defaults to persist — and this job pip-installs Aviato with `contents: write`), and reusable-release-gate.yml:56-59 has a `with:` block (fetch-depth/fetch-tags) but no `persist-credentials: false`. Add to both. — FINDINGS #6 (narrowed) · .github/workflows/reusable-consumer-automation.yml:73; reusable-release-gate.yml:56-59
- [med] SECURITY.md now documents `AVIATO_SETTINGS_TOKEN`, but reusable-consumer-automation.yml:6 still carries the false header comment "no stored secret (platform token only, §6.6)" while lines 26-34 of the same file define the settings-token secret. Fix the header comment. — FINDINGS #60 (narrowed) · .github/workflows/reusable-consumer-automation.yml:6,26-34

## Settled — do not reopen

- §11.3 detector semantics are frozen: bashlex-AST taint, fail-closed, block-level verify. NO interpreter enumeration, any-word matching, order-aware verify, grep mirrors, or a second in-workflow checker (8d069f7, accf092, faaeb10, 66951ba, 9ccea23). The same impl runs in every consumer's CI via reusable-common-lint.yml — single implementation, no mirror to drift.
- zizmor scope decision (#18): the gate covers `unpinned-uses`, `unpinned-images`, and `template-injection`; `dangerous-triggers` stays non-gating (recorded in zizmor.yml + SECURITY.md + §11.3).
- npm/Node hardening is only ever strengthened, never relaxed (S6).
