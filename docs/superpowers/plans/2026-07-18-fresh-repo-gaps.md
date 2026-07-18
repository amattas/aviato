# Fresh-Repo Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three process gaps the 2026-07-18 live proofs filed: fresh repos can't run release automation (Actions PR permission), stale classic protection outlives a declared override (dual-control), and fresh python repos start CI-red (no package skeleton).

**Architecture:** Task A adds a fourth settings group (`actions:`) through the existing generic settings pipeline (new GitHub endpoint, same flat-dict flow). Task B makes `apply_settings` clear conflicting classic PR-review protection when a matching modeled ruleset owns the branch — loudly, in the returned messages, within the already operator-consented paths. Task C adds seed-once package-skeleton artifacts, unlocked by teaching `resolved_artifacts` to render `output_path` through the same strict template pass bodies get (pathguard still confines the result at write time).

**Tech Stack:** Python 3.12 (`aviato` conda env), pytest, strict gate `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh`.

## Global Constraints

- Branch: `feat/fresh-repo-gaps` off current main. TDD mandatory (failing test → implement → green). Never push; controller handles push/PR.
- Run tools via `PATH=/opt/homebrew/Caskroom/miniforge/base/envs/aviato/bin:$PATH`.
- Lint every touched file with BOTH `ruff format --check` and `black --check --line-length 120 --target-version py312` (they disagree on wrapped assert-messages — keep asserts single-line ≤120 chars).
- Core agnosticism (§9b): `aviato/core/*` must not name platforms/languages — the flat settings key strings live in data (baseline.yaml) and the binding, never hardcoded in core; scaffold/onboarding path changes stay generic.
- Commit messages: Conventional Commits, body ending with a blank line then `Claude-Session: https://claude.ai/code/session_01U3pYYKSatz7Agu8XYKtXTc`.
- Each task's final step removes its corresponding Open item from the module backlog (onboarding / reconcile / scaffolding) in the same commit — completed work lives in git history, not backlogs.

---

### Task A: `can_approve_pull_request_reviews` as a managed setting

**Files:**
- Modify: `aviato/library/bundles/settings/baseline.yaml` (new `actions:` group after `repository:`)
- Modify: `aviato/github.py` (new read helper near `repo_merge_methods`, line ~229)
- Modify: `aviato/github_platform.py` (`_ACTIONS_SETTING_KEYS`, `map_actions_settings`, `to_actions_payload`, `read_settings` merge at ~501, `apply_settings` PUT after the repository PATCH at ~1043, `RECONCILABLE_SETTING_KEYS` union at ~435)
- Modify: `docs/requirements/modules/onboarding/backlog.md` (remove the Open item)
- Test: `tests/test_github_platform.py`

**Interfaces:**
- Produces: flat key `can_approve_pull_request_reviews` (bool) in the settings dict; read via `GET repos/{slug}/actions/permissions/workflow`, applied via `PUT repos/{slug}/actions/permissions/workflow` with body `{"can_approve_pull_request_reviews": <bool>}`. Baseline desires `true` (release automation opens its own release PRs). `_check_baseline_settings_keys` in validation auto-accepts via the RECONCILABLE union; fakeplatform and core need no changes (generic dicts).

- [ ] **Step 1 (RED):** Add tests mirroring the repository-settings pair: `test_map_actions_settings_from_live` (live perms dict with the key + an unrelated key → only the modeled key mapped), `test_to_actions_payload_subset_and_shape` (subset behavior, `{}` → `{}`); extend `test_read_settings_composes_gh_responses` (monkeypatch a new `github.actions_workflow_permissions` returning `{"can_approve_pull_request_reviews": False}`, assert it lands in the settings dict) and the apply-settings test that verifies issued gh calls to assert a `PUT repos/o/r/actions/permissions/workflow` when the key is in the payload. Run: expect FAIL (helpers missing).
- [ ] **Step 2 (GREEN):** Implement per the interfaces above: `github.actions_workflow_permissions(slug)` (mirror `repo_merge_methods`: `gh_json_optional`, keep only modeled keys); the two builders iterating `_ACTIONS_SETTING_KEYS`; merge into `read_settings`; in `apply_settings`, build `to_actions_payload(payload)` and, when non-empty, `PUT` it (plain fail-loud like the repository PATCH — this endpoint has no feature gating); union into `RECONCILABLE_SETTING_KEYS`.
- [ ] **Step 3:** Add the baseline group with a comment in the established voice:
```yaml
  # GitHub Actions workflow permissions (PUT /repos/{owner}/{repo}/actions/permissions/workflow).
  # The release automation opens its own release PRs; fresh repos ship with this OFF, which
  # broke release-PR creation on every new consumer (2026-07-18 live proofs) — managed as
  # desired state so provisioning sets it and §5.6/§5.7 catch a repo that flips it back.
  actions:
    can_approve_pull_request_reviews: true
```
- [ ] **Step 4:** Run `python3 -m pytest tests/test_github_platform.py tests/core/test_settingsdrift.py tests/test_cli_provision.py -q` (all green) and `python3 -m aviato.cli validate` (clean). Remove the onboarding backlog Open item. Commit: `feat(settings): manage the Actions can-approve-PRs permission through the baseline`.

### Task B: clear conflicting classic protection when a ruleset owns the branch

**Files:**
- Modify: `aviato/github_platform.py:1017-1032` (the modeled-ruleset-owns branch of `apply_settings`)
- Modify: `docs/requirements/modules/reconcile/backlog.md` (remove the Open item)
- Test: `tests/test_github_platform.py` (apply-settings coverage), `tests/test_cli_provision.py` (complete-protection path)

**Interfaces:**
- Consumes: `apply_settings` already reads live classic protection (~line 945) and detects ruleset ownership via `_MODELED_RULE_TYPES`.
- Produces: when a modeled ruleset owns branch protection AND live classic protection still carries `required_pull_request_reviews`, apply issues `DELETE repos/{repo}/branches/{branch}/protection/required_pull_request_reviews` and APPENDS a message to the returned list, e.g. `"cleared conflicting classic PR-review protection on <branch>: the branch ruleset owns §5.7 enforcement"`. A DELETE failure is surfaced as an error message, never swallowed. Behavior is identical in both consented callers (reconcile, complete-protection).

- [ ] **Step 1 (RED):** In the existing apply-settings test family, add/extend a case: live state has a matching modeled ruleset AND classic protection with `required_pull_request_reviews.required_approving_review_count: 1`; desired `required_reviews: 0`. Assert (a) the DELETE call is issued to the exact endpoint, (b) the returned messages include the cleared-protection notice. Add the negative: no classic PR-review block present → no DELETE. Run: FAIL.
- [ ] **Step 2 (GREEN):** Implement in the ruleset-owns early-return branch (both the matches-desired and after-write paths — the clear must happen whenever the ruleset owns enforcement and classic conflicts, not only when drift-free). Keep it scoped to the `required_pull_request_reviews` sub-resource — do NOT delete whole-branch classic protection (other classic fields like force-push blocks may be intentionally layered).
- [ ] **Step 3:** Extend `test_complete_protection_applies_full_desired` (tests/test_cli_provision.py) so the fake platform starts with conflicting classic protection and the test asserts the clear happens through the CLI path. Run the file green.
- [ ] **Step 4:** Validate clean; remove the reconcile backlog Open item. Commit: `fix(settings): clear conflicting classic PR-review protection once a ruleset owns the branch`.

### Task C: package-skeleton seeds (+ templated `output_path`)

**Files:**
- Modify: `aviato/core/onboarding.py` (~line 189-191: render `template.output_path` with the same strict `render(..., render_vars)` used for bodies)
- Create: `aviato/library/scaffold/python-package-init.yaml` → `output_path: "{{ import-name }}/__init__.py"`, `source: files/package-init.py.txt`, `seed_once: true`
- Create: `aviato/library/scaffold/python-test-skeleton.yaml` → `output_path: tests/test_package.py`, `source: files/test_package.py.txt`, `seed_once: true`
- Create: `aviato/library/scaffold/python-requirements.yaml` → `output_path: requirements.txt`, `source: files/requirements.txt.txt`, `seed_once: true` (service profile only)
- Create the three `aviato/library/scaffold/files/*.txt` bodies (below)
- Modify: `aviato/library/bundles/scaffold/python-library-sc.yaml`, `python-component-sc.yaml` (add package-init + test-skeleton), `python-service-sc.yaml` (add all three)
- Modify: `docs/requirements/modules/scaffolding/backlog.md` (remove the skeleton Open item; keep the node-majors item)
- Test: `tests/core/test_onboarding.py`, `tests/core/test_scaffold.py`

**Interfaces:**
- `files/package-init.py.txt`:
```python
"""{{ distribution-name }}."""
```
- `files/test_package.py.txt` (must satisfy `mypy --strict`):
```python
"""Seed-once starter test — replace with real tests (the developer owns this file)."""

import {{ import-name }}


def test_package_imports() -> None:
    assert {{ import-name }}.__doc__ is not None
```
- `files/requirements.txt.txt`:
```
# Runtime dependencies (consumer-owned; installed by CI and the Dockerfile when present).
```
- `resolved_artifacts` renders `output_path` strictly (unknown variable → the existing strict-render error); the write path's existing pathguard confinement rejects escaping results.

- [ ] **Step 1 (RED, core):** In `tests/core/test_onboarding.py`, add `test_output_path_renders_template_variables` — a registry artifact with `output_path: "{{ import-name }}/__init__.py"` resolves to `pkg/__init__.py` when `import-name=pkg`. And `test_output_path_escaping_variable_is_refused` — `import-name="../escape"` must raise (from strict render or the pathguard at materialization; assert whichever layer fires, and that it FIRES). Run: FAIL.
- [ ] **Step 2 (GREEN, core):** Render `template.output_path` through the same strict render as the body in `resolved_artifacts` (generic — no profile/language knowledge in core). If pathguard does not already reject `../` outputs at materialization, extend `confined_target` usage to cover resolved outputs (cite: scaffold write path).
- [ ] **Step 3 (RED, data):** Add `test_python_profiles_seed_package_skeleton` (parameterized over python-library/python-component/python-service) asserting resolved artifacts include the seeded `__init__.py` under the import-name dir and `tests/test_package.py`, both `seed_once`, and (service only) `requirements.txt`. Run: FAIL.
- [ ] **Step 4 (GREEN, data):** Create the descriptors/bodies and register them in the three `-sc.yaml` bundles.
- [ ] **Step 5:** Sanity-run the seeded test body's semantics locally: render it for a dummy import name into a temp dir with an `__init__.py` and run `mypy --strict` + `pytest` on the pair (a scratch check, not a committed test) — record the result in the report. Full file runs green; `aviato validate` clean (lint-actions accepts the new seeds — no pins in them). Remove the scaffolding backlog skeleton item. Commit: `feat(scaffold): seed a CI-green package skeleton for python profiles`.

### Task D (controller): gate, PR, wrap
- [ ] Full strict gate green; push `feat/fresh-repo-gaps`; one PR with auto-merge; release train (0.5.0 — Task A/C are feats) follows the usual dance.
