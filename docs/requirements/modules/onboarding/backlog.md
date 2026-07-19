# Onboarding backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [process] The scaffolded callers hardcode the verify commands (install-command "python -m pip install -e .[dev]", etc.) with no declared variable to override them — a consumer whose layout differs can only edit the managed caller (perpetual drift). Live evidence: pydmp's cli-extra/test coupling would have been a one-variable fix, and OVERLAY already predicts calendar-mcp needs a custom install command (no pyproject at root). Expose the verify command set (install/lint/test/build) as optional profile variables with the current literals as defaults. — source: 2026-07-19 pydmp adoption · aviato/library/scaffold/files/wf-python-library.yml
- [process] Consumers with GitHub's default-setup CodeQL enabled fail the security baseline cryptically (GitHub rejects advanced-configuration SARIF while default setup is on — live: pydmp PR #44's first run). The baseline OWNS CodeQL for consumers, so default setup must be `not-configured`: probe it in `aviato doctor`'s §17 remote prerequisites (GET /repos/{owner}/{repo}/code-scanning/default-setup) and document the disable step in the onboarding runbook (PATCH state=not-configured). — source: 2026-07-19 pydmp adoption · .github/workflows/reusable-security-baseline.yml
- [process] `onboard --write`/`sync` render artifacts from the INSTALLED tool's bundled library while `--pin` governs the callers' remote refs and the drift automation's render source — §2.6 sanctions same-major skew, but when scaffold bodies change between minors the skew silently manufactures phantom drift on every changed artifact (live: a 0.5.2 CLI onboarding pydmp with `--pin 0.5.0` wrote root-layout docs artifacts a 0.5.0-pinned drift run would flag wholesale). Minimum fix: warn loudly at write time when tool version != pin, naming the repin/re-pin-flag remedies; a fuller fix (render fresh onboards from the fetched pin registry, as §5.12 repin already does) trades away offline scaffolding and needs its own design pass. — source: 2026-07-18 pydmp adoption · aviato/cli.py (§2.6 check site has both versions in hand)


## Settled — do not reopen

- (none)
