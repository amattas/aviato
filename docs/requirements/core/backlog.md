# Core backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [med] validate()'s monotonic-alias parity check runs the embedded highest.py snippet via `subprocess.run([sys.executable, "-c", snippet, candidate])` with no timeout — it can hang a CI gate. `command.run`'s DEFAULT_TIMEOUT_SECONDS does not cover this direct call. Add a timeout there. — FINDINGS #10 (narrowed) · aviato/validation.py:634 (called from cli.py:231)
- [low] §8.15 secret guard is type/name-based only; a token pasted into a plain (non-secret) variable or `overrides` persists undetected. The contract is now documented (variables.py:65-70, SECURITY.md:99); remaining optional work is a warn-only content heuristic. — FINDINGS #17 · aviato/core/variables.py:65-70
- [med] Library typing migration is only partial — the main package is `mypy --strict`, but test files stay outside the gate (`files=["aviato"]`) and are flagged "tests pending". Bring tests under strict typing. — FINDINGS #38 (narrowed) · aviato/library/aviato-library.yaml:8,11; python-library.yaml:11-12; pyproject.toml:58; .github/aviato.yaml:7-8
- [low] `amattas/aviato` slug hardcoded across the tree incl. the agnostic core, with no centralizing data source or drift check. Centralize as data + add a drift check for the YAML/workflow copies. — FINDINGS #41 · aviato/validation.py:65; cli.py:57; plugins/actionpins.py:15; library/zizmor.yml:23; core/onboarding.py:61
- [low] ⚖ Consumer scaffold templates still declare Python 3.11 after the py312 bump (Library files done). Decision (2026-06-09): bump `requires-python` >=3.12 and move ruff/black targets py311→py312 everywhere — apply it to the scaffold templates. — FINDINGS #45 (narrowed) · aviato/library/scaffold/files/pyproject.toml.txt:10; ruff.toml.txt:2
- [low] The §11.3 pin gate (`action_pin_violations`) globs only seeded scaffold templates, not the Library's own pyproject.toml — root dev extras are exact-pinned today but ungated, so a future float goes undetected. Extend the gate to check root pyproject.toml extras via `unpinned_pyproject_extra_lines`. — FINDINGS #46 (narrowed) · aviato/plugins/actionpins.py:923-925; pyproject.toml:24-40
- [low] Only one FakePlatform is asserted against the Platform protocol (test_ports.py:13-14, method presence not signatures); three test doubles drift: test_cli_reconcile.py `_FakePlatform.apply_settings` returns None not `list[str]`; test_cli_drift_report.py `FakePlatform.apply_settings` lacks `expected_live`/return type and is missing `revoke_consent`/`create_repo`; test_cli_provision.py `_FakePlatform.apply_settings` lacks `expected_live`. — FINDINGS #54 (narrowed) · tests/core/test_ports.py:13-14; test_cli_reconcile.py; test_cli_drift_report.py; test_cli_provision.py
- [med] Many load-bearing CLI flags remain undocumented in README (only onboard `--open-pr`/`--docs` and apply-rulesets `--declaration` were added): `--write`, `--migrate-profile`, `--allow-dirty`, `--var`, `--public`, `--override-version-pin`, scan `--fix`/`--audit`, offboard `--delete-files`. — FINDINGS #63 (narrowed) · README.md; aviato/cli.py:2009-2144
- [low] onboard plan output omits the environment prerequisites (pypi/ghcr/app-store-connect) derivable from `resolved.pipeline_modules`; doctor already surfaces these (cli.py:803). Originally mislabeled as docs — the fix is to add the environments section to the plan. — FINDINGS #66 (narrowed) · aviato/cli.py:719-759 (cf. doctor cli.py:803)
- [low] superpowers plans/specs read as 0%-done to future sessions; add implemented-status headers. The 2026-07-11 docs-restructure plan lacks the `**STATUS: IMPLEMENTED**` header the 2026-05-21/2026-05-29 plans carry. — FINDINGS #67 · docs/superpowers/plans/2026-07-11-docs-restructure.md
- [low] Stale "mirrors" framing for the §11.3 pin gate persists in the requirements text ("no grep mirror — the two-implementation drift was R9-5") after ARCHITECTURE.md/SECURITY.md were corrected to single-implementation language. — FINDINGS #68 (narrowed) · docs/requirements/modules/security/supply-chain.md (§11.3, was REQUIREMENTS.md:1444)

## Settled — do not reopen

- Agnostic core: new capabilities land as data/plugins, never as core edits that name a specific target (language/registry/tool). If a change seems to need editing `aviato/core/*.py` to add a target, the abstraction is wrong (§4.3, §9b selfcheck).
