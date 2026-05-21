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

Note: `validate.sh` runs pytest with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. Tests must not depend on third-party pytest plugins. `shellcheck` and `actionlint` are skipped (not failed) when not installed locally; CI installs them.

CLI surface (entrypoint `aviato.cli:main`):

```bash
aviato audit .                              # discover + audit repos under a local root
aviato audit --repo /path/to/repo           # audit one explicit local repo
aviato apply-rulesets OWNER/REPO            # dry-run rulesets
aviato apply-rulesets OWNER/REPO --apply    # apply rulesets
aviato apply-rulesets OWNER/REPO --required-approvals 0 --apply  # solo-repo override
aviato render-rulesets                       # print rendered ruleset JSON
aviato onboard OWNER/REPO --profile python-library  # composition-backed onboarding plan
aviato doctor /path/to/consumer              # classify a consumer's managed artifacts (§5.4)
aviato sync /path/to/consumer                # materialize managed artifacts from its declaration (§5.3)
aviato validate                              # validate this repo's policy infra + core agnosticism
```

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
(§5.3/§6.3 seed-once + sidecar), `diagnosis` (§5.4), `filedrift` (§5.5),
`settingsdrift` (§5.6), `consent` (§5.8 fail-closed gate), `version`/`compatibility`
(§2.6), `versioning` (§5.9 Conventional Commit bump), `bootstrap` (§5.10),
`onboarding` (§5.2), `repin` (§5.12), `offboarding` (§5.13), `selfcheck` (§9b).
Process flows reference `REQUIREMENTS.md` section numbers in docstrings — keep
them accurate when changing behavior.

### policy.yml is the single source of truth

`policy.yml` owns policy constants — most importantly the release tag pattern (`^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta)[0-9]+)?$`) and default required PR approvals. That pattern is **intentionally duplicated** into several places that need a literal at definition time:

- `.github/actions/validate-release-ref/action.yml` (the `tag-pattern` input default)
- every release workflow in `RELEASE_WORKFLOWS` (embeds the literal so validation is pinned to the same ref)
- rendered ruleset payloads (injected at render time, not stored)

`aviato/validation.py` enforces these copies stay in sync via drift checks. **When you change the tag pattern or any embedded constant, update `policy.yml` and let validation tell you every copy that drifted — never treat docs or a workflow as the source of truth.** Docs (`README.md`, `ARCHITECTURE.md`, `REQUIREMENTS.md`) describe policy but are not authoritative.

### Rendering pipeline (policy → rulesets)

`rulesets.yml` is a manifest mapping each ruleset JSON template in `rulesets/` to a target (`branch`/`tag`) and a `patch` of dotted policy paths to inject. `aviato/rulesets.py` deep-copies the JSON template and patches values from `policy.yml` (or a `--required-approvals` override) at render time. `apply_rulesets` then upserts each rendered payload to GitHub. To add a ruleset: add the JSON template, register it in `rulesets.yml`, and (if required) add it to `REQUIRED_FILES` in `validation.py`.

### GitHub access is via the `gh` CLI only

`aviato/github.py` shells out to `gh api` (through `aviato/command.py`'s `run` helper) for every GitHub interaction — there is no SDK or token handling in code. Read calls use `allow_error=True` to degrade gracefully (audit rows show `API_ERROR`/`NO_REMOTE`); `upsert_ruleset` finds an existing ruleset by name and PUTs vs POSTs accordingly.

### Validation is the gate

`aviato/validation.py` (`validate()`) is what CI runs and what guards correctness. It checks required files exist, YAML/JSON parse, `policy.yml` examples actually match/reject the pattern, pattern drift across embedded copies, template `uses:` references point at workflows that exist, and that release workflows are tag-only (no `release/*`, no checkout by repository name, must reference `GITHUB_REF_TYPE`/`tag`). Adding a new required workflow/file or release workflow means updating `REQUIRED_FILES` / `RELEASE_WORKFLOWS`.

### Reusable workflows share one command contract

All language CI workflows (`reusable-python-ci`, `reusable-node-ci`, `reusable-swift-ci`) expose the same inputs: `working-directory`, `install-command`, `lint-command`, `test-command`, `build-command`, and the `run-*` toggles. Keep this contract identical across languages; unsupported steps use an empty command and a disabled default. `templates/profile-*.yml` compose these reusable workflows for a repo shape and must stay thin (select workflow + supply inputs, no duplicated release/protection logic). Profiles are defined in code in `aviato/profiles.py`.

## Conventions

- **Terminology:** use "default branch", not "main" (main is only an example). Rulesets target `~DEFAULT_BRANCH`; report fields use names like `default_branch_requires_pr`.
- **Release publishing is tag-only.** Legacy `release/*` / `release/latest` branches are migration artifacts and are rejected by validation — do not add branch-based release support.
- Ruleset JSON files stay readable templates; policy values are injected, not hardcoded.
- `catalog.md` and `repos-*.txt` are operator working artifacts, not committed library state.
