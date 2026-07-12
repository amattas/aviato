# PyPI deployment backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [med] `upload-artifact@v7` (reusable-pypi-publish.yml:247) ↔ `download-artifact@v8` (:301) on the dist/SBOM handoff are still mismatched majors — improved from the original v7↔v4, but this release-path pair should share a major. Align. — FINDINGS #15 (narrowed) · .github/workflows/reusable-pypi-publish.yml:247,301
- [high] PyPI trusted publishing is structurally impossible for CONSUMER repos through the shared cross-repo `reusable-pypi-publish.yml`: the OIDC `job_workflow_ref` claim resolves to `amattas/aviato/...` (the workflow file containing the publish job) which can never match a consumer's registered publisher (observed live, 0.2.2 run 27309044125 → `invalid-publisher`). wf-python-library.yml:79 still calls the shared workflow; no consumer-side publish wrapper exists in the library (only in starter/python-library/release.yml). Fix (option a): scaffold a thin in-consumer-repo publish workflow body (the gh-action-pypi-publish step lives in the consumer repo; Aviato logic stays upstream). Touches scaffold bundle + pipelines.yaml + §13.1 + onboarding docs. — FINDINGS F-3 · aviato/library/scaffold/files/wf-python-library.yml:79

## Settled — do not reopen

- pip-audit stays `--strict`; no severity filter (R7-1: pip-audit JSON carries no severity).
