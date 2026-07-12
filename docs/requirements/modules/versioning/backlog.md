# Versioning backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [low] §5.9 mermaid flowchart still reads "Advance floating major reference UNCONDITIONALLY", contradicting the `is-highest` monotonic guard the workflow applies (reusable-release.yml) and the narrative text (already reworded to "guarded monotonically per §8.14"). Reword the diagram node. — FINDINGS #57 (narrowed) · docs/requirements/modules/versioning/release.md (§5.9 diagram, was REQUIREMENTS.md:821)
- [med] Release-PR required checks stay BLOCKED under rulesets: GitHub doesn't surface `workflow_dispatch` check runs in a PR's status rollup, so the §5.9 propose-phase dispatch passes on the commit but the ruleset's required contexts read "expected". Durable fix (operator-verified by design — needs a release-capable pass): a caller-side dispatch-only job (`statuses: write`, `if: always()`, `needs` ci/security/common-lint) mirroring each pipeline's `status_check` context as a commit STATUS on `github.sha`, with context strings bound to `pipelines.yaml` by a guard test. Touches 5 wf-* caller bodies + regen + sync + §5.9. Interim mitigation in place: `bypass_actors` (RepositoryRole admin, `pull_request` mode) on the branch ruleset. — FINDINGS F-1

## Settled — do not reopen

- Release gate keeps `merge-base --is-ancestor` (R6-4); fixes may ADD SHA-binding, never re-tighten to tip equality.
- Tag-only release publishing; no stored release PAT; fail-closed `aviato-ref` (no `main` default).
- C12-W1 release privilege split (FINDINGS #2) is implemented: derive job runs `contents: read` with no token; only the propose/tag job holds `contents: write` + `pull-requests: write`; top-level `permissions: {}` (reusable-release.yml:71-200). The documented, accepted residual — the write job still installs the pinned Aviato with the write token ambient because a step cannot drop job permissions (defense-in-depth for the heavy derive phase, not elimination) — is recorded at reusable-release.yml:27-29 and SECURITY.md. Do not reopen.
