# Fleet backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [low] doctor still reports drift automation by local file presence, not API enabled-state — the API probe exists (`drift_automation_enabled`, github_platform.py:627-661) but is never read: diagnosis.py:203 sets `drift_automation_present` from local files and cli.py:826 prints that, so a manually-disabled workflow reads healthy. Wire the probed state into `report.drift_automation_present`. — FINDINGS #31 (narrowed) · aviato/core/diagnosis.py:203; cli.py:804-826; github_platform.py:627-661
- [low] Two `diagnose()` call sites omit the §5.4 `prerequisite_paths`/`drift_automation_markers` probes (the fleet scan path was fixed): scan `--fix` (`_propose_file_drift`) and drift-report. Pass both there too. — FINDINGS #33 (narrowed) · aviato/cli.py:1017; cli.py:1643

## Settled — do not reopen

- (none)
