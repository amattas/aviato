# Adoption Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every open backlog item that gates using Aviato across the fleet (the pydmp pilot and the migrations behind it), so `aviato onboard` runs against a proven library.

**Architecture:** Three kinds of work, phased: (1) pure code tasks (a managed `allow_auto_merge` setting; four §11.3 pin-parity guards in `validation.py`) done TDD on a branch and shipped in release 0.4.x; (2) operator-gated live actions against amattas/aviato itself (settings reconcile, SEC-010 canary evidence); (3) disposable-repo live proofs of the three deploy pipelines (TestPyPI §13.1, docs Pages §13.3, GHCR §13.2) followed by the §13.5 rollback/yank runbook, each closing its backlog item with recorded evidence.

**Tech Stack:** Python 3.12 (`mamba activate aviato`), pytest, `./scripts/validate.sh` strict gate, `gh` CLI, GitHub reusable workflows.

## Global Constraints

- Requires-python `>=3.12`; run tools via the `aviato` conda env (`PATH=/opt/homebrew/Caskroom/miniforge/base/envs/aviato/bin:$PATH`).
- Gate before every commit: `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh` must pass (compile, validate, ruff, black --line-length 120, mypy --strict, pytest, build, yamllint, shellcheck, actionlint).
- Core stays agnostic (§9b): never name a language/registry in `aviato/core/`; the selfcheck denylist enforces this.
- Release tag pattern: `^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(alpha|beta)[0-9]+)?$` (policy.yml is the single source of truth).
- Privileged GitHub changes are operator-initiated, never unattended (§2). Tasks marked **[OPERATOR]** need the human at the wheel; agents prepare commands and record evidence only.
- Conventional Commits; batch pushes (each phase = one push/PR, not one per task).
- Every task that closes a backlog item ends by moving that item to the file's `## Settled — do not reopen` section (or recording evidence links in `docs/requirements/traceability.md`) in the same commit as the work.

## Backlog Disposition Map

| Open item | Task | Deferred? |
|---|---|---|
| security: auto-merge via settings baseline | 2, 7 | |
| security: §11.3 unguarded pin surfaces | 3–6 | |
| security: SEC-010 canary evidence | 8 | |
| security: SEC-010 Dependabot security updates + doctor | 7 | |
| security: pypa `release/v1` pin watch | — | watch-only; re-check each dep audit |
| pypi: TestPyPI proof §13.1 | 9 | |
| docs-site: Pages proof §13.3 | 10 | |
| docs-site: mike-fork watch | — | watch-only until Zensical ships versioning |
| ghcr: multi-arch proof §13.2 + Trivy 0.72 rider | 11 | |
| deployment: §11.6/§13.5 rollback/yank proof | 12 | |
| apple: §13.4 App Store proof | — | deferred until law18/OKRocket migrate (Tier 2) |
| scaffolding: node seed majors live proof | — | executes itself on the first node-service scaffold (phase-3 fleet work) |

---

## Phase 0 — Ship the fixed library

### Task 1: Merge PR #78 and publish 0.4.0 **[OPERATOR]**

**Files:** none (GitHub operations).

- [ ] **Step 1: Merge PR #78** (test fixes + dependency-matrix refresh; CI must be green first)

```bash
gh pr checks 78 --repo amattas/aviato   # expect all pass
gh pr merge 78 --repo amattas/aviato --squash   # or your preferred method
```

- [ ] **Step 2: Watch the release PR regenerate.** The release automation recomputes the next version from Conventional Commits on the main push. PR #76 (`chore(release): 0.4.0`) should update/recreate and its `ci / Python CI` check — previously failing on the hardcoded-version test — should now pass.

```bash
gh pr list --repo amattas/aviato --state open
gh pr checks 76 --repo amattas/aviato    # expect: all green now
```

- [ ] **Step 3: Merge the release PR, confirm the published release**

```bash
gh pr merge 76 --repo amattas/aviato --squash
gh release view 0.4.0 --repo amattas/aviato   # expect: release exists, tag 0.4.0
```

Expected: `0.4.0` published. This is the pin every subsequent `aviato provision --pin 0.4.0` uses.

---

## Phase 1 — Code work (one branch: `feat/adoption-readiness-guards`, one PR at phase end)

### Task 2: `allow_auto_merge` as a managed repository setting

**Files:**
- Modify: `aviato/github.py:225` (MERGE_METHOD_KEYS tuple)
- Modify: `aviato/library/bundles/settings/baseline.yaml:35-43` (repository group)
- Test: `tests/test_github_platform.py:743,758,1077`

**Interfaces:**
- Produces: `allow_auto_merge` flows through `repo_merge_methods()` → `map_repository_settings()` → `read_settings()`, and `to_repository_payload()` → `PATCH /repos/{slug}` — all generic over `MERGE_METHOD_KEYS`; no other code changes. `RECONCILABLE_SETTING_KEYS` and `_check_baseline_settings_keys` auto-inherit.

- [ ] **Step 1: Write the failing tests** — extend the three existing tests in `tests/test_github_platform.py` (do not add sibling tests; these three already own the behavior):

In `test_map_repository_settings_from_live` (line 743), add the new key to the fixture and expectation:

```python
    repo = {
        "allow_merge_commit": True,
        "allow_squash_merge": False,
        "allow_auto_merge": True,
        # allow_rebase_merge absent → omitted (never a false destructive), like map_security_settings
        "unrelated": 1,
    }
    assert map_repository_settings(repo) == {
        "allow_merge_commit": True,
        "allow_squash_merge": False,
        "allow_auto_merge": True,
    }
```

In `test_to_repository_payload_subset_and_shape` (line 758):

```python
    payload = to_repository_payload({"allow_merge_commit": True, "allow_auto_merge": True})
    assert payload == {"allow_merge_commit": True, "allow_auto_merge": True}
    assert "allow_rebase_merge" not in payload
    assert to_repository_payload({}) == {}
```

In `test_read_settings_includes_merge_methods` (line 1077), add the key to the monkeypatched read and assert it:

```python
    monkeypatch.setattr(
        github,
        "repo_merge_methods",
        lambda repo: {
            "allow_merge_commit": False,
            "allow_squash_merge": True,
            "allow_rebase_merge": True,
            "allow_auto_merge": False,
        },
    )
    settings = GitHubPlatform().read_settings("o/r")
    ...
    assert settings["allow_auto_merge"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_github_platform.py -q -k "repository_settings or repository_payload or merge_methods"
```
Expected: FAIL — `map_repository_settings` drops `allow_auto_merge` (not in the tuple).

- [ ] **Step 3: Implement — one line in `aviato/github.py:225`**

```python
# Canonical repo-level PR toggle keys (top-level booleans on GET/PATCH /repos/{owner}/{repo}).
# allow_auto_merge rides along: same GET/PATCH shape as the merge-method toggles (§5.6/§5.7).
# github_platform derives _REPOSITORY_SETTING_KEYS from this tuple — one copy, no drift.
MERGE_METHOD_KEYS = ("allow_merge_commit", "allow_squash_merge", "allow_rebase_merge", "allow_auto_merge")
```

- [ ] **Step 4: Add the baseline key** in `aviato/library/bundles/settings/baseline.yaml` (repository group), and extend the group comment:

```yaml
  # Repo-level PR toggles, reconciled by §5.6/§5.7 (read + diff + apply). GitHub returns these
  # as top-level booleans on the repo GET and accepts them 1:1 on the repo PATCH. Managed for
  # fleet consistency (operator decisions 2026-07-11 and 2026-07-16): all merge methods enabled,
  # and auto-merge enabled so dependabot PRs converge unattended under strict up-to-date
  # required checks (see security backlog, 2026-07-16 dependabot triage).
  repository:
    allow_merge_commit: true
    allow_squash_merge: true
    allow_rebase_merge: true
    allow_auto_merge: true
```

- [ ] **Step 5: Run the tests and the settings-keys validation**

```bash
python3 -m pytest tests/test_github_platform.py tests/core/test_settingsdrift.py tests/core/test_reconcile.py -q
python3 -m aviato.cli validate
```
Expected: PASS / `Aviato validation passed.` (`_check_baseline_settings_keys` accepts the key because `RECONCILABLE_SETTING_KEYS` inherits it.)

- [ ] **Step 6: Move the security-backlog auto-merge item's *implementation half* forward** — edit `docs/requirements/modules/security/backlog.md`: annotate the auto-merge entry with `(baseline capability landed <commit>; live apply tracked by the reconcile step)` — it moves to Settled only after Task 7 applies it live.

- [ ] **Step 7: Commit**

```bash
git add aviato/github.py aviato/library/bundles/settings/baseline.yaml tests/test_github_platform.py docs/requirements/modules/security/backlog.md
git commit -m "feat(settings): manage allow_auto_merge through the settings baseline"
```

### Task 3: §11.3 guard (a) — scaffold seed dev-pins must match the Library's own pins

**Files:**
- Modify: `aviato/validation.py` (new `_check_seed_dev_pin_parity`, wired into `validate()` after `_check_scaffold_constant_parity` at line ~1019; add `import tomllib` at top)
- Test: `tests/test_validation_negative.py`

**Interfaces:**
- Consumes: `validate()`'s `errors: list[str]` convention; the `repo_copy` fixture (tests/test_validation_negative.py:36-40).
- Produces: error strings containing `differs from the Library's own pyproject.toml` and `(§11.3)`.

- [ ] **Step 1: Write the failing test** (mirror `test_docs_toolchain_pin_drift_is_flagged`, line 613):

```python
def test_seed_dev_pin_drift_from_library_pyproject_is_flagged(repo_copy: Path) -> None:
    # §11.3 guard (a): seeds must track the Library's own gate toolchain pins.
    target = repo_copy / "aviato" / "library" / "scaffold" / "files" / "requirements-dev.txt.txt"
    text = target.read_text(encoding="utf-8")
    drifted = re.sub(r"^mypy==[0-9.]+$", "mypy==1.0.0", text, count=1, flags=re.MULTILINE)
    assert drifted != text, "fixture did not contain a mypy pin"
    target.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("differs from the Library's own pyproject.toml" in e and "mypy" in e for e in errors), errors
```

- [ ] **Step 2: Run it — expect FAIL** (`validate()` returns no such error yet):
`python3 -m pytest tests/test_validation_negative.py::test_seed_dev_pin_drift_from_library_pyproject_is_flagged -q`

- [ ] **Step 3: Implement** in `aviato/validation.py`:

```python
def _check_seed_dev_pin_parity(root: Path, errors: list[str]) -> None:
    """§11.3: scaffold seed dev-tool pins must equal the Library's own pyproject [dev] pins.

    The seeds are what new consumers start on; letting them float independently is how they
    ended up a full mypy major stale (2026-07-16 audit). Only tools present in BOTH places
    are compared — seeds intentionally omit Library-only tools (black, yamllint, ...).
    """
    canonical: dict[str, str] = {}
    with (root / "pyproject.toml").open("rb") as handle:
        for entry in tomllib.load(handle)["project"]["optional-dependencies"]["dev"]:
            name, _, version = entry.partition("==")
            if version:
                canonical[name.lower()] = version
    pin_re = re.compile(r'^\s*"?([A-Za-z0-9._-]+)==([0-9][0-9A-Za-z.]*)"?,?\s*$')
    for rel in ("pyproject.toml.txt", "requirements-dev.txt.txt"):
        seed = root / "aviato" / "library" / "scaffold" / "files" / rel
        for line in seed.read_text(encoding="utf-8").splitlines():
            match = pin_re.match(line)
            if match is None:
                continue
            name, version = match.group(1).lower(), match.group(2)
            expected = canonical.get(name)
            if expected is not None and version != expected:
                errors.append(
                    f"aviato/library/scaffold/files/{rel}: {name} pin {version!r} differs from the "
                    f"Library's own pyproject.toml pin {expected!r} (§11.3)"
                )
```

Wire into `validate()` directly after the `_check_scaffold_constant_parity(root, errors)` line.

- [ ] **Step 4: Run the test (PASS) + positive path** (`test_repository_validates_clean` still green):
`python3 -m pytest tests/test_validation_negative.py tests/test_validation.py -q`

- [ ] **Step 5: Commit** — `git commit -m "feat(validate): guard scaffold seed dev-pins against Library pyproject drift (§11.3)"`

### Task 4: §11.3 guard (b) — starter/** hash-pins must match root workflow pins

**Files:**
- Modify: `aviato/validation.py` (new `_check_starter_action_pin_parity`, wired after Task 3's check)
- Test: `tests/test_validation_negative.py`

**Interfaces:**
- Produces: error strings containing `but .github/workflows pins` and `(§11.3)`. Only 40-hex digest pins are compared (tag pins like `actions/checkout@v7` are first-party-exempt and skipped by the regex); keyed by action `owner/repo` so `trivy-action` never compares against `setup-trivy`.

- [ ] **Step 1: Write the failing test**:

```python
def test_starter_action_pin_drift_from_root_workflows_is_flagged(repo_copy: Path) -> None:
    # §11.3 guard (b): starter masters must pin the same digests as the root workflows.
    target = repo_copy / "starter" / "container-service" / "release.yml"
    text = target.read_text(encoding="utf-8")
    drifted = text.replace(
        "docker/login-action@af1e73f918a031802d376d3c8bbc3fe56130a9b0",
        "docker/login-action@" + "0" * 40,
    )
    assert drifted != text, "fixture did not contain the expected login-action digest"
    target.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("docker/login-action" in e and ".github/workflows pins" in e for e in errors), errors
```

- [ ] **Step 2: Run it — expect FAIL.**

- [ ] **Step 3: Implement**:

```python
_HASH_PIN_USES_RE = re.compile(r"uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/[^@\s]+)?@([0-9a-f]{40})\b")


def _check_starter_action_pin_parity(root: Path, errors: list[str]) -> None:
    """§11.3: a third-party action hash-pinned in starter/** must carry the same digest as the
    root workflows' pin for that action. starter/ is outside dependabot and lint-actions reach
    (2026-07-16 audit found a v3-commented v4 digest there); parity to the root pins — which ARE
    dependabot-bumped — is the drift guard."""
    canonical: dict[str, set[str]] = {}
    for wf in sorted((root / ".github" / "workflows").glob("*.yml")):
        for action, sha in _HASH_PIN_USES_RE.findall(wf.read_text(encoding="utf-8")):
            canonical.setdefault(action, set()).add(sha)
    for starter_file in sorted((root / "starter").rglob("*.yml")):
        for action, sha in _HASH_PIN_USES_RE.findall(starter_file.read_text(encoding="utf-8")):
            expected = canonical.get(action)
            if expected and sha not in expected:
                errors.append(
                    f"{starter_file.relative_to(root)}: {action} pinned to {sha} but "
                    f".github/workflows pins {sorted(expected)} (§11.3)"
                )
```

- [ ] **Step 4: Run test (PASS) + clean positive path.** Note: if the clean run flags a real pre-existing mismatch, that is a genuine finding — fix the pin, don't weaken the check.

- [ ] **Step 5: Commit** — `git commit -m "feat(validate): guard starter action digests against root workflow drift (§11.3)"`

### Task 5: §11.3 guard (c) — canonical Trivy CLI pin in policy.yml

**Files:**
- Modify: `aviato/library/policy.yml` (new `tools:` block)
- Modify: `aviato/validation.py` (new `_check_trivy_pin_parity(root, policy, errors)`)
- Test: `tests/test_validation_negative.py`

**Interfaces:**
- Produces: `policy["tools"]["trivy_version"]` (e.g. `"v0.72.0"`); error strings containing `Trivy CLI version` and `(§11.3)`. Binds the OPERATIVE `version:` line under the setup-trivy step (like `_check_release_pattern_drift` binds `TAG_PATTERN`), so a stale comment can't mask drift.

- [ ] **Step 1: Add the canonical value** to `aviato/library/policy.yml`:

```yaml
tools:
  # §11.3: single source of truth for the Trivy CLI version the GHCR publish workflow installs
  # (aquasecurity/setup-trivy `version:` input). Bump here; validation binds the workflow copy.
  trivy_version: "v0.72.0"
```

- [ ] **Step 2: Write the failing test**:

```python
def test_trivy_cli_version_drift_from_policy_is_flagged(repo_copy: Path) -> None:
    # §11.3 guard (c): the setup-trivy version input must match policy.yml's tools.trivy_version.
    target = repo_copy / ".github" / "workflows" / "reusable-docker-ghcr.yml"
    text = target.read_text(encoding="utf-8")
    drifted = text.replace("version: v0.72.0", "version: v0.55.0", 1)
    assert drifted != text, "fixture did not contain the expected Trivy CLI version input"
    target.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("Trivy CLI version" in e for e in errors), errors
```

- [ ] **Step 3: Run it — expect FAIL.**

- [ ] **Step 4: Implement**:

```python
def _check_trivy_pin_parity(root: Path, policy: dict[str, Any], errors: list[str]) -> None:
    """§11.3: the GHCR workflow's setup-trivy `version:` input must equal policy.yml's
    tools.trivy_version — the only tool version installed via an action INPUT rather than a
    pinned uses:/pip literal, so no other check sees it (2026-07-16 audit)."""
    expected = str(policy.get("tools", {}).get("trivy_version", ""))
    if not expected:
        errors.append("policy.yml is missing tools.trivy_version (§11.3)")
        return
    wf = root / ".github" / "workflows" / "reusable-docker-ghcr.yml"
    match = re.search(
        r"uses:\s*aquasecurity/setup-trivy@[0-9a-f]{40}[^\n]*\n\s+with:\n\s+version:\s*(\S+)",
        wf.read_text(encoding="utf-8"),
    )
    if match is None:
        errors.append(f"{wf.relative_to(root)}: no setup-trivy version input found to bind (§11.3)")
    elif match.group(1) != expected:
        errors.append(
            f"{wf.relative_to(root)}: Trivy CLI version {match.group(1)!r} differs from "
            f"policy.yml tools.trivy_version {expected!r} (§11.3)"
        )
```

Wire into `validate()` (it already has `policy` in scope): `_check_trivy_pin_parity(root, policy, errors)`.

- [ ] **Step 5: Run test (PASS) + positive path. Commit** — `git commit -m "feat(validate): bind the Trivy CLI version input to policy.yml (§11.3)"`

### Task 6: §11.3 guard (d) — node seed devDependency parity

**Files:**
- Modify: `aviato/validation.py` (new `_check_node_seed_devdep_parity`)
- Test: `tests/test_validation_negative.py`

- [ ] **Step 1: Write the failing test**:

```python
def test_node_seed_devdep_drift_between_variants_is_flagged(repo_copy: Path) -> None:
    # §11.3 guard (d): the ts/js seed manifests must agree on shared devDependency ranges.
    target = repo_copy / "aviato" / "library" / "scaffold" / "files" / "package.json.js.txt"
    text = target.read_text(encoding="utf-8")
    drifted = text.replace('"eslint": "^10.0.0"', '"eslint": "^9.0.0"', 1)
    assert drifted != text, "fixture did not contain the expected eslint range"
    target.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("node seed devDependencies differ" in e and "eslint" in e for e in errors), errors
```

- [ ] **Step 2: Run it — expect FAIL.**

- [ ] **Step 3: Implement**:

```python
def _check_node_seed_devdep_parity(root: Path, errors: list[str]) -> None:
    """§11.3: the two node seed manifests must agree on every shared devDependency range —
    they are each other's only comparison source (same pattern as the python-version
    all-copies-agree leg of _check_scaffold_constant_parity)."""
    scaffold_dir = root / "aviato" / "library" / "scaffold" / "files"
    deps: dict[str, dict[str, str]] = {}
    for rel in ("package.json.ts.txt", "package.json.js.txt"):
        deps[rel] = json.loads((scaffold_dir / rel).read_text(encoding="utf-8")).get("devDependencies", {})
    ts, js = deps["package.json.ts.txt"], deps["package.json.js.txt"]
    for pkg in sorted(set(ts) & set(js)):
        if ts[pkg] != js[pkg]:
            errors.append(
                f"node seed devDependencies differ for {pkg!r}: package.json.ts.txt={ts[pkg]!r} "
                f"vs package.json.js.txt={js[pkg]!r} (§11.3)"
            )
```

- [ ] **Step 4: Run test (PASS) + positive path.**

- [ ] **Step 5: Close the backlog item + full gate + PR.** Move the §11.3 unguarded-pin-surfaces entry in `docs/requirements/modules/security/backlog.md` to Settled with a note: `guards (a)-(d) landed <commit>; remaining un-automatable surface (dependabot cannot watch starter/ workflow files) is covered by the starter↔root parity guard`. Then:

```bash
AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh    # full strict gate, expect green
git add -A && git commit -m "feat(validate): node seed devDependency parity + close §11.3 surfaces backlog item"
git push -u origin feat/adoption-readiness-guards
gh pr create --title "feat: adoption-readiness guards (auto-merge baseline + §11.3 pin parity)" \
  --body "Closes two security-backlog items: allow_auto_merge lands as a managed settings-baseline key (one-line binding change; live apply follows via the §5.7 reconcile flow), and the four §11.3 pin surfaces the 2026-07-16 audit found unguarded get validation parity checks (seed dev-pins vs Library pyproject, starter digests vs root workflows, Trivy CLI input vs policy.yml, node seed devDependency parity). TDD throughout; strict gate green."
```

---

## Phase 2 — Live actions on amattas/aviato **[OPERATOR]**

### Task 7: Reconcile aviato's own settings (auto-merge + Dependabot security updates) and run doctor

Prereq: Phase 1 merged to main (reconcile runs from the local checkout; no release needed).

- [ ] **Step 1: Produce the settings diff** (expect two changes: `allow_auto_merge false→true`, `dependency_scanning false→true`):

```bash
aviato drift-report . --settings-only --require-settings
```

- [ ] **Step 2: Follow the §5.6→§5.7 path**: create/locate the settings-drift tracking issue the flow names, then apply with the diff-bound confirmation:

```bash
aviato reconcile . <ISSUE_NUMBER> --confirm <DIFF_ID>
```

- [ ] **Step 3: Verify live state**:

```bash
gh api repos/amattas/aviato --jq '{allow_auto_merge, security_and_analysis}'
```
Expected: `allow_auto_merge: true`, `dependabot_security_updates.status: "enabled"`.

- [ ] **Step 4: Run doctor and record**: `aviato doctor .` — record every healthy/degraded/externally-blocked line verbatim (do not convert warnings to success).

- [ ] **Step 5: Close the two backlog items** — move the auto-merge entry and the `[live rollout]` Dependabot entry in `docs/requirements/modules/security/backlog.md` to Settled, citing the issue number, diff id, and doctor output. Commit as `docs(security): record auto-merge + dependabot-updates rollout evidence`.

### Task 8: SEC-010 canary — capture the ruleset-block evidence, then clean up

Current state (verified 2026-07-16): PR #59 is CLOSED but its branch `codex/codeql-blocking-canary` still exists; critical alert #23 (`py/code-injection`, `aviato/_codeql_canary.py:13`) exists; the workflow-gate failure evidence exists (run 29218873903, job 86720007061) but the NATIVE ruleset block (protect-default-branch.json `code_scanning` rule, `security_alerts_threshold: high_or_higher`) was never captured, and the close happened before the authorized cleanup checkpoint.

- [ ] **Step 1: Reopen the canary** — `gh pr reopen 59 --repo amattas/aviato` — and wait for checks to finish (`gh pr checks 59 --watch`).

- [ ] **Step 2: Capture the durable evidence** (save all outputs; these are the artifacts):

```bash
gh pr view 59 --repo amattas/aviato --json mergeable,mergeStateStatus     # expect BLOCKED
gh api graphql -f query='query { repository(owner:"amattas", name:"aviato") {
  pullRequest(number:59) { mergeStateStatus reviewDecision
    commits(last:1){nodes{commit{statusCheckRollup{state}}}} } } }'
gh api repos/amattas/aviato/code-scanning/alerts/23                       # critical, open
```
The proof: `mergeStateStatus == BLOCKED` while all *required status checks* pass except the security gate — i.e. the ruleset's `code_scanning` rule (not just the workflow step) is what blocks. If the API exposes rule-level failures (`gh api repos/amattas/aviato/commits/<head-sha>/status` + branch-ruleset endpoints), capture those too.

- [ ] **Step 3: Record it** — update `docs/requirements/traceability.md` SEC-010 row: replace "Final ruleset proof remains in the security backlog" with links to the PR, alert #23, the gate-failure job, and the captured BLOCKED state. Move the `[live verification]` canary entry in `docs/requirements/modules/security/backlog.md` to Settled.

- [ ] **Step 4: Cleanup (authorized checkpoint)** — close PR #59, delete the branch, confirm the alert closes:

```bash
gh pr close 59 --repo amattas/aviato
git push origin --delete codex/codeql-blocking-canary
gh api repos/amattas/aviato/code-scanning/alerts/23 --jq .state   # expect closed/fixed once ref is gone
```

- [ ] **Step 5: Commit the docs** — `docs(security): record SEC-010 canary ruleset-block evidence and close the item`.

---

## Phase 3 — Deploy-pipeline live proofs **[OPERATOR]** (9, 10, 11 are independent; 12 last)

### Task 9: §13.1 TestPyPI trusted-publishing proof (on amattas/aviato itself)

aviato is already wired: `aviato-ci.yml` has the consumer-local `pypi-publish` job; the `pypi` environment exists but has **no required reviewer** and **no endpoint variables**. Real-PyPI publishes already work (0.3.0 is live) — only the TestPyPI half of the §13.1 DoD is open.

- [ ] **Step 1: Set the environment's required reviewer** (README prerequisite):

```bash
gh api user --jq .id    # your user id (expected 10504740)
gh api --method PUT repos/amattas/aviato/environments/pypi \
  --input - <<'JSON'
{"reviewers":[{"type":"User","id":10504740}]}
JSON
```

- [ ] **Step 2: Register the TestPyPI trusted publisher** (web UI, out-of-band): on test.pypi.org → Publishing → add a *pending* publisher for project `aviato`: owner `amattas`, repository `aviato`, workflow `aviato-ci.yml`, environment `pypi`. (The name `aviato` is unclaimed on TestPyPI — verified 2026-07-16.)

- [ ] **Step 3: Point the pipeline at TestPyPI — environment-scoped, and REMOVE IT AFTER.** While this variable is set, EVERY publish from this repo goes to TestPyPI:

```bash
gh api --method POST repos/amattas/aviato/environments/pypi/variables \
  -f name=PYPI_REPOSITORY_URL -f value=https://test.pypi.org/legacy/
```

- [ ] **Step 4: Cut a dev-suffixed release** (§11.6 hygiene; PEP 440 normalizes `-alpha1`→`a1`): tag the released 0.4.0 commit's successor as `0.4.1-alpha1` via the normal release flow (or `git tag 0.4.1-alpha1 && git push origin 0.4.1-alpha1` if tag-push is the trigger), approve the `pypi` environment gate when prompted.

- [ ] **Step 5: Verify §13.1's full DoD** from the run + index:
  - run log: OIDC publish succeeded, both fresh-tag re-verifications passed, PEP 691 confirmation gate found every filename+sha256;
  - `curl -s https://test.pypi.org/pypi/aviato/json | jq .info.version` → `0.4.1a1`;
  - installability: `python -m pip install --index-url https://test.pypi.org/simple/ --no-deps aviato==0.4.1a1` into a scratch env;
  - provenance: `gh attestation verify <downloaded-wheel> --owner amattas`.

- [ ] **Step 6: CLEANUP — remove the redirect first**, then yank (the yank doubles as the §13.5 PyPI leg — save the evidence for Task 12):

```bash
gh api --method DELETE repos/amattas/aviato/environments/pypi/variables/PYPI_REPOSITORY_URL
# then on test.pypi.org UI: yank 0.4.1a1 (record screenshot/URL)
gh api repos/amattas/aviato/environments/pypi/variables   # expect: empty — CONFIRM the redirect is gone
```

- [ ] **Step 7: Record** — move the pypi backlog item to Settled with run/index/attestation links; note the §13.1 DoD (TestPyPI half) is met. Commit `docs(pypi): record §13.1 TestPyPI trusted-publishing proof`.

### Task 10: §13.3 docs-site Pages proof (disposable repo)

- [ ] **Step 1: Provision** a disposable consumer with docs enabled and Pages serving on:

```bash
aviato provision amattas/aviato-proof-docs --profile python-library --pin 0.4.0 --docs --var serve-pages=true
gh api --method POST repos/amattas/aviato-proof-docs/pages -f build_type=workflow
```
(If the `serve-pages` variable name differs, check `aviato/library/python-library.yaml`'s variables block.)

- [ ] **Step 2: Release 0.1.0** on the disposable repo (tag-push through its scaffolded flow) and let the docs pipeline run.

- [ ] **Step 3: Verify the DoD from the docs branch alone**: branch contains `0.1.0/` version directory; `latest` alias points at it. Then on the served site: `latest` resolves at the root, Zensical search returns results, Mermaid renders, `/sitemap.xml` present.

- [ ] **Step 4: Prove the monotonic guard**: release `0.2.0` (latest MUST move), then `0.1.1` (latest MUST NOT move; run log shows the highest.py guard skipping the alias). This is the §8.14/§13.2-shared comparator's live proof.

- [ ] **Step 5: Record + cleanup** — capture branch tree listing, site URLs, run links; move the docs-site `[external verification]` item to Settled; delete the repo (`gh repo delete amattas/aviato-proof-docs --yes`). Commit `docs(docs-site): record §13.3 Pages proof`.

### Task 11: §13.2 GHCR multi-arch proof + Trivy 0.72 rider (disposable repo)

- [ ] **Step 1: Provision** with a container profile and multi-arch platforms:

```bash
aviato provision amattas/aviato-proof-ghcr --profile python-service --pin 0.4.0
```
Then set `platforms: "linux/amd64,linux/arm64"` in the scaffolded caller (input on the GHCR job; check the caller — the input defaults to `linux/amd64`).

- [ ] **Step 2: Add the operator-provided Dockerfile** (never seeded — §R5-6), minimal:

```dockerfile
FROM python:3.12-slim
COPY . /app
WORKDIR /app
CMD ["python", "-c", "print('aviato ghcr proof')"]
```

- [ ] **Step 3: Release 0.1.0** and verify from the run + registry:
  - per-platform build→scan→push with **byte identity**: skopeo local digest == pushed digest for each arch (job log);
  - **Trivy 0.72 rider**: SARIF upload appears in the repo's code-scanning tab; the HIGH/CRITICAL gate ran (exit code path exercised);
  - SBOM artifact `aviato-image-sboms` present; provenance: `gh attestation verify oci://ghcr.io/amattas/aviato-proof-ghcr:0.1.0 --owner amattas`;
  - manifest references only the scanned digests.

- [ ] **Step 4: Prove the monotonic alias**: release `0.2.0` (`latest` moves), then `0.1.1` (`latest` stays).

- [ ] **Step 5: Record + §13.5 GHCR leg + cleanup**: capture digests/attestation/SARIF links; then — as the rollback demo — delete the `0.2.0` package version and re-point `latest` to `0.1.0` via `gh api` (record commands + before/after), demonstrate the floating-major de-advance on the repo's major ref. Move BOTH ghcr backlog items to Settled. Delete package + repo. Commit `docs(ghcr): record §13.2 multi-arch proof and Trivy 0.72 verification`.

### Task 12: §13.5/§11.6 rollback-yank runbook completion

- [ ] **Step 1: Consolidate the three legs** already exercised: PyPI yank (Task 9 step 6), GHCR delete/retag + major de-advance (Task 11 step 5), docs-site n/a (docs branch is git-revertable — note that as the documented mechanism). Write them up per target as the "documented per target" §13.5 requires — a short runbook section in `docs/specifications/modules/deployment/` or an appendix in `docs/requirements/modules/deployment/README.md` §13.5.

- [ ] **Step 2: Close the item**: move the deployment backlog `[external verification]` entry to Settled; update the §13.5 traceability row's notes. Commit `docs(deployment): record §13.5 rollback/yank runbook evidence`.

---

## Phase 4 — Decisions and final sweep

### Task 13: PR #64 disposition **[OPERATOR decision]**

Recommendation: **close unmerged and harvest.** Grounds: it conflicts with main, its own body forbids treating it as readiness evidence, it excludes 12 follow-up files, its CI fails (SEC-011 traceability), and main now onboards cleanly without it — while it *deletes* the scaffold caller bodies Phase 1 just guarded.

- [ ] **Step 1:** `gh pr close 64 --repo amattas/aviato --comment "Superseded by the adoption-readiness plan (2026-07-16): main onboards cleanly; harvesting transition/protection/inventory modules as focused follow-ups."` Keep the branch for harvest.
- [ ] **Step 2:** File one tracking issue listing the harvestable pieces (`core/transition.py`, `core/protection.py`, `core/compiler.py`, `core/ruleset_plan.py`, `core/inventory.py`, privileged-review workflow) with the PR #64 branch as source.

### Task 14: Final backlog sweep and gate

- [ ] **Step 1:** Confirm every module backlog's `## Open` is either empty or contains only the explicitly deferred items (apple §13.4, pypa watch, mike watch, node-seed proof): `grep -A5 "^## Open" docs/requirements/modules/**/backlog.md`.
- [ ] **Step 2:** Full gate: `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh` green; report exact counts.
- [ ] **Step 3:** Declare adoption-ready: the pydmp pilot can start per the corrected OVERLAY.md (registration = workflow `aviato-ci.yml`, environment `pypi`; docs already Zensical).
