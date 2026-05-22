# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Aviato is a reusable GitHub policy, CI, release, and onboarding conventions library. It ships reusable Actions workflows, ruleset payloads, caller templates, and an operator-run Python CLI (`aviato`). It deliberately keeps **no persistent inventory of consumer repositories** — audits and onboarding always target a local root or one explicit repo, and privileged changes are operator-initiated, never unattended.

## Commands

```bash
python3 -m pip install -e .[dev]   # install CLI + dev tools (pytest, ruff)
./scripts/validate.sh              # full local gate: compile, validate, ruff, pytest, shellcheck, actionlint
python3 -m pytest                  # run tests
python3 -m pytest tests/test_rulesets.py::test_rendered_tag_ruleset_uses_policy_pattern  # single test
ruff check . && ruff format --check .
```

Note: `validate.sh` runs pytest with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. Tests must not depend on third-party pytest plugins. `ruff`/`pytest`/`shellcheck`/`actionlint` are skipped when not installed locally, but the run ends with a **loud banner** listing every skipped tool (because CI runs them — a green local gate with skips does **not** mean CI is green). Run with `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh` for CI-parity: a missing tool then fails the gate. CI installs all of them.

CLI surface (entrypoint `aviato.cli:main`):

```bash
aviato audit .                              # discover + audit repos under a local root
aviato audit --repo /path/to/repo           # audit one explicit local repo
aviato apply-rulesets OWNER/REPO            # dry-run rulesets
aviato apply-rulesets OWNER/REPO --apply    # apply rulesets
aviato apply-rulesets OWNER/REPO --required-approvals 0 --apply  # solo-repo override
aviato render-rulesets                       # print rendered ruleset JSON
aviato onboard PATH --profile python-library [--write --allow-dirty --var k=v]  # plan, or adopt a local repo (§5.2)
aviato doctor /path/to/consumer              # classify managed artifacts + probe health (§5.4)
aviato sync /path/to/consumer                # materialize managed artifacts incl. caller workflows (§5.3/§15)
aviato scan /path/a /path/b [--fix]          # fleet diagnosis; --fix opens managed-file proposals (§5.11/§5.5)
aviato drift-report /path/to/consumer [--file-only|--settings-only] [--require-settings]  # file + settings drift (§5.5/§5.6); --require-settings exits non-zero if settings can't be read
aviato reconcile /path/to/consumer <issue> --confirm <diff-id>  # operator-gated settings apply, diff-bound (§5.7)
aviato complete-protection /path/to/consumer # idempotently (re-)apply full branch protection (§5.2 recovery)
aviato repin /path/to/consumer X.Y.Z [--write]  # move the Library version pin (§5.12)
aviato offboard /path/to/consumer [--write --delete-files | --open-pr]  # remove from Aviato mgmt; --open-pr opens a reviewable removal proposal (§5.13)
aviato next-version --current 1.2.3 --commit "feat: x"  # SemVer from Conventional Commits (§5.9)
aviato bump-version 1.3.0 /path/to/consumer  # write version into version-source locations (§3.3)
aviato validate                              # validate policy infra + agnosticism + digest pins + template parity + inline monotonic-alias parity
```

**Onboarding materializes the caller workflows.** A profile's scaffold bundle includes
the `.github/workflows/aviato-ci.yml` (verify/release/deploy/security) and
`aviato-drift.yml` (scheduled drift/report) callers, so `sync`/`onboard --write` give a
consumer the actual workflows required by §15 — not just composed pipeline names. Caller
workflows live as packaged bodies under `aviato/library/scaffold/files/wf-*.yml` — these
are the **authoritative source**. The top-level `templates/profile-*.yml` and
`templates/consumer-automation.yml` are documented copyable EXAMPLES **rendered from**
those scaffold bodies (run `python3 scripts/regen-templates.py` after editing a caller);
`aviato validate` fails if they drift (`_check_template_scaffold_parity`).

`scripts/audit-repos.sh` and `scripts/apply-rulesets.sh` are thin compatibility wrappers that exec the CLI.

## Architecture

### The agnostic core engine (`aviato/core/`) vs. plug-in data

`REQUIREMENTS.md` mandates a composition of plug-in modules around an **agnostic
core** (§2.1). The core lives in `aviato/core/` and must contain **no** language-
or deployment-specific logic. Day-zero specifics (Python/Node/Swift, PyPI/GHCR/
Pages/Apple) live as **data** in `profiles/`, `bundles/{workflows,scaffold,settings}/`,
and `templates/scaffold/` — the §5.10 module-source tree — loaded by
`aviato/core/registry.py` and resolved by `aviato/core/composition.py` into a
`ResolvedSet`.

**The agnosticism is falsifiable and enforced (§9b).** `aviato/core/selfcheck.py`
fails if any `aviato/core/*.py` (a) imports `aviato.plugins`, or (b) contains a
denylisted identifier (the list is **data** at `aviato/plugins/denylist.txt`, not
hardcoded — so the checker's own source carries none of the words it scans for).
This runs inside `aviato validate`. **When adding a capability, add a module/data —
never put `python`/`ruff`/`ghcr`/etc. into core code.** If a change seems to need
editing core to add a target, the abstraction is wrong (§4.3). Comment-syntax
knowledge that names extensions (e.g. `.swift`) lives in
`aviato/plugins/comment_syntax.py`, not core, for the same reason.

Core module map: `composition` (§5.1/§4.2 resolution), `declaration` (§6.1),
`variables` (§5.2/§6.6 + §8.15 secret guard), `marker` (§6.2), `scaffold`
(§5.3/§6.3 seed-once + sidecar), `diagnosis` (§5.4), `filedrift`/`settingsdrift`
(§5.5/§5.6 primitives), `consent` (§5.8 fail-closed gate), `reconcile` (§5.7
decision logic), `version` (§2.6 compatibility), `versioning` (§5.9 Conventional
Commit bump), `bootstrap` (§5.10), `onboarding` (§5.2), `repin` (§5.12),
`offboarding` (§5.13), `selfcheck` (§9b).

**Orchestration vs. binding (§2.14).** The platform-touching flows are split:
the *decision/orchestration* logic lives in core (`settings_drift_flow` §5.6,
`file_drift_flow` §5.5, `reconcile_flow` §5.7, `fleet` §5.11) and depends only on
the `Platform` **port** (`core/ports.py`) — so it's unit-tested against an
in-memory fake (`tests/core/fakeplatform.py`). The concrete GitHub binding is
`aviato/github_platform.py` (outside core; may name `gh`), composing the tested
`github.py` helpers. **The live end-to-end runs of these flows, and the Part II
deploy pipelines (PyPI/GHCR/Pages/Apple), are operator-verified by design**
(§9.2/§9.9/§13.4.7) — the engine primitives and the GitHub binding's
response-mapping are tested, but a real GitHub repo + credentials are needed to
exercise them live. Process flows reference `REQUIREMENTS.md` section numbers in
docstrings — keep them accurate when changing behavior.

### policy.yml is the single source of truth

`policy.yml` owns policy constants — most importantly the release tag pattern (`^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta)[0-9]+)?$`) and default required PR approvals. That pattern is **intentionally duplicated** into several places that need a literal at definition time:

- every release workflow in `RELEASE_WORKFLOWS` (embeds the literal in its `TAG_PATTERN` env so validation is pinned to the same ref)
- rendered ruleset payloads (injected at render time, not stored)

`aviato/validation.py` enforces these copies stay in sync via drift checks. **When you change the tag pattern or any embedded constant, update `policy.yml` and let validation tell you every copy that drifted — never treat docs or a workflow as the source of truth.** Docs (`README.md`, `ARCHITECTURE.md`, `REQUIREMENTS.md`) describe policy but are not authoritative.

### Rendering pipeline (policy → rulesets)

`rulesets.yml` is a manifest mapping each ruleset JSON template in `rulesets/` to a target (`branch`/`tag`) and a `patch` of dotted policy paths to inject. `aviato/rulesets.py` deep-copies the JSON template and patches values from `policy.yml` (or a `--required-approvals` override) at render time. `apply_rulesets` then upserts each rendered payload to GitHub. To add a ruleset: add the JSON template, register it in `rulesets.yml`, and (if required) add it to `REQUIRED_FILES` in `validation.py`.

### GitHub access is via the `gh` CLI only

`aviato/github.py` shells out to `gh api` (through `aviato/command.py`'s `run` helper) for every GitHub interaction — there is no SDK or token handling in code. Read calls use `allow_error=True` to degrade gracefully (audit rows show `API_ERROR`/`NO_REMOTE`); `upsert_ruleset` finds an existing ruleset by name and PUTs vs POSTs accordingly.

### Validation is the gate

`aviato/validation.py` (`validate()`) is what CI runs and what guards correctness. It checks required files exist, YAML/JSON parse, `policy.yml` examples actually match/reject the pattern, pattern drift across embedded copies, template `uses:` references point at workflows that exist, release workflows are tag-only (no `release/*`, no checkout by repository name, must reference `GITHUB_REF_TYPE`/`tag`), third-party actions/tools are digest-pinned (§11.3, `_check_action_pins`), the `templates/profile-*.yml` examples match the rendered scaffold (`_check_template_scaffold_parity`), and the inline `highest.py` heredocs embedded in the GHCR/Pages deploy workflows still agree with `core.versioning.is_highest` (§8.14/§13.2, `_check_monotonic_alias_parity` — runs the snippet against a battery of cases so a hand-copied comparator can't silently drift). Adding a new required workflow/file or release workflow means updating `REQUIRED_FILES` / `RELEASE_WORKFLOWS`.

### Reusable workflows share one command contract

All language CI workflows (`reusable-python-ci`, `reusable-node-ci`, `reusable-swift-ci`) expose the same inputs: `working-directory`, `install-command`, `lint-command`, `test-command`, `build-command`, and the `run-*` toggles. Keep this contract identical across languages; unsupported steps use an empty command and a disabled default. The `templates/profile-*.yml` examples compose these reusable workflows for a repo shape and stay thin (select workflow + supply inputs, no duplicated release/protection logic); they are rendered from the scaffold bodies (see "Onboarding materializes the caller workflows"), not hand-edited.

## Conventions

- **Terminology:** use "default branch", not "main" (main is only an example). Rulesets target `~DEFAULT_BRANCH`; report fields use names like `default_branch_requires_pr`.
- **Release publishing is tag-only.** Legacy `release/*` / `release/latest` branches are migration artifacts and are rejected by validation — do not add branch-based release support.
- Ruleset JSON files stay readable templates; policy values are injected, not hardcoded.
- `catalog.md` and `repos-*.txt` are operator working artifacts, not committed library state.
