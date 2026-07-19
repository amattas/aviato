# Onboarding backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [process] `onboard --write`/`sync` render artifacts from the INSTALLED tool's bundled library while `--pin` governs the callers' remote refs and the drift automation's render source — §2.6 sanctions same-major skew, but when scaffold bodies change between minors the skew silently manufactures phantom drift on every changed artifact (live: a 0.5.2 CLI onboarding pydmp with `--pin 0.5.0` wrote root-layout docs artifacts a 0.5.0-pinned drift run would flag wholesale). Minimum fix: warn loudly at write time when tool version != pin, naming the repin/re-pin-flag remedies; a fuller fix (render fresh onboards from the fetched pin registry, as §5.12 repin already does) trades away offline scaffolding and needs its own design pass. — source: 2026-07-18 pydmp adoption · aviato/cli.py (§2.6 check site has both versions in hand)
- [process] The declaration is `.github/aviato.yaml` while everything else in a consumer's `.github/` is `.yml` (17 workflows + dependabot) — an undocumented accident (library data itself splits 8 `.yaml`/3 `.yml`), not a decision. Decide the convention: either document `.yaml` as deliberate, or teach the loader to accept both with one canonical form; a hard rename is a §6.1 consumer-contract break (path is hardcoded in core/declaration.py, callers, docs, and trusted-publisher instructions) and would need a dual-read migration window across adopted repos. — source: 2026-07-18 pydmp adoption review · aviato/core/declaration.py:16


## Settled — do not reopen

- (none)
