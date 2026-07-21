# Versioning backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [process] next-version maps a BREAKING CHANGE to a MAJOR bump even on the 0.x line, but the operator policy (decision 2026-07-19, first exercised on the aviato.yml rename) is to hold 0.x — breaking changes bump the MINOR until the operator deliberately promotes 1.0. Teach next-version 0.x semantics (or an explicit promote-to-1.0 switch); until then each 0.x breaking release needs the operator-cut override (close the automation's release PR, bump-version + hand-cut tag, as done for 0.6.0). The override runbook must ALSO include `gh release create <tag>` — the hand-cut path skips the release job's in-run creation step (reusable-release.yml), which is how 0.6.0/0.6.1 shipped tags with no GitHub Release until the operator backfilled 0.6.1 on 2026-07-21. — source: 2026-07-19 release #103 override · aviato/core/versioning.py


## Settled — do not reopen

- Release gate keeps `merge-base --is-ancestor` (R6-4); fixes may ADD SHA-binding, never re-tighten to tip equality.
- Tag-only release publishing; no stored release PAT; fail-closed `aviato-ref` (no `main` default).
- C12-W1 release privilege split (FINDINGS #2) is implemented: derive job runs `contents: read` with no token; only the propose/tag job holds `contents: write` + `pull-requests: write`; top-level `permissions: {}` (reusable-release.yml:71-200). The accepted ambient-token residual is recorded in `docs/security/threat-model.md` and the workflow rationale. Do not reopen.
