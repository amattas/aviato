# Onboarding backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [low] `provision` bypasses the OWNER/REPO slug validation that onboard/offboard/repin `--open-pr` use (`_proposal_slug`/`is_owner_repo_slug`): it takes `args.slug` directly, checks only `"/" in slug`, and passes it unvalidated to `gh repo clone`, so a malformed slug like `a/b/c` reaches clone. Validate with `is_owner_repo_slug`. — FINDINGS #23 (narrowed) · aviato/cli.py:1456-1506 (slug 1464, weak check 1465-1467, clone 1506)
- [med] `apply-rulesets` fails the entire apply when `tag_name_pattern` returns `422` — GitHub's metadata-restriction rules (tag/branch/commit-message patterns) are Enterprise-only, so personal/Free repos reject it (observed live on amattas/aviato). Detect the 422-on-metadata-rule case and degrade with a loud warning (or add a `--no-pattern-rules` flag) instead of failing the whole apply; document the plan requirement in README/§settings. Tag immutability (deletion + non_fast_forward) still applies degraded. — FINDINGS F-2 · aviato/github.py `upsert_ruleset`; cli.py `cmd_apply_rulesets`

## Settled — do not reopen

- (none)
