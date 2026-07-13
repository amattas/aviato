# Tag Ruleset String-List 422 Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Aviato handle GitHub's observed string-list unsupported-tag-rule 422 without broadening the fail-closed downgrade boundary, then prove and record exact live ruleset convergence.

**Architecture:** Extend only `_unsupported_tag_metadata_rule` with a whole-entry matcher for the exact live string form. Reuse the existing single degraded retry and payload-copy path; no new retry loop or error-normalization layer. After automated verification, reapply from the hotfix worktree, assert both live rulesets, reconcile durable documentation, and prune this plan and its design before publishing one PR.

**Tech Stack:** Python 3.12+, pytest, `gh` CLI, Markdown governance records, GitHub repository rulesets.

## Global Constraints

- The combined response must contain `HTTP 422` before any degraded retry is permitted.
- A string error entry matches only the case-insensitive whole-entry grammar `^\s*invalid\s+rule\s+["']tag_name_pattern["']\s*:\s*$`.
- Inspect one error entry at a time; never correlate text across separate entries.
- Keep existing structured object handling unchanged.
- The degraded retry occurs at most once and removes only `tag_name_pattern` from a deep copy.
- Preserve `bypass_actors: []`, targeting conditions, enforcement, deletion, and non-fast-forward protection.
- Propagate permission, authentication, network, server, malformed-response, other-rule, parameter-validation, and degraded-retry failures.
- Do not change or merge PR #59 or release PR #42.
- Do not weaken the now-zero-bypass branch ruleset or recreate an admin bypass.
- Remove completed work from the security backlog and update traceability only after exact live readback succeeds.
- Remove this plan and `docs/superpowers/specs/2026-07-13-tag-ruleset-string-422-design.md` from the final branch tip after durable facts are incorporated.
- Push the branch once and open one PR; merging requires approval by a reviewer other than the author.

---

### Task 1: Classify the exact live string-list rejection

**Files:**
- Modify: `tests/test_github.py:259-341`
- Modify: `aviato/github.py:363-410`

**Interfaces:**
- Consumes: `_unsupported_tag_metadata_rule(stderr: str) -> bool`, `_without_tag_name_pattern(payload)`, and `upsert_ruleset(...)`.
- Produces: exact string-entry classification while preserving `RulesetApplyResult.degraded_rules == ("tag_name_pattern",)` and the existing one-retry contract.

- [ ] **Step 1: Consolidate the stdout regression around both supported structured shapes**

Replace `test_upsert_ruleset_reads_structured_unsupported_tag_error_from_stdout` with this parameterized test so the object form stays covered and the exact live string form fails before implementation:

```python
@pytest.mark.parametrize(
    "structured",
    (
        '{"message":"Validation Failed","errors":['
        '{"field":"rules/2/type","value":"tag_name_pattern","code":"invalid"}]}',
        '{"message":"Validation Failed","errors":["Invalid rule \'tag_name_pattern\': "]}',
    ),
    ids=("object-entry", "live-string-entry"),
)
def test_upsert_ruleset_reads_structured_unsupported_tag_error_from_stdout(
    monkeypatch: pytest.MonkeyPatch,
    structured: str,
) -> None:
    payload = _tag_ruleset_payload()
    monkeypatch.setattr(
        github,
        "repository_rulesets",
        lambda slug: [{"name": "Common: release tag format", "target": "tag", "id": 42}],
    )
    calls: list[list[str]] = []
    submitted: list[JsonObject] = []
    payload_paths: list[Path] = []
    payload_modes: list[int] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        submitted.append(_capture_payload(cmd))
        path = Path(cmd[cmd.index("--input") + 1])
        payload_paths.append(path)
        payload_modes.append(path.stat().st_mode & 0o777)
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 1, structured, "gh: Validation Failed (HTTP 422)")
        return subprocess.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(github, "run", fake_run)

    result = github.upsert_ruleset("o/r", payload, apply=True)

    assert result.degraded_rules == ("tag_name_pattern",)
    assert len(calls) == 2
    assert submitted[0] == payload
    rules = cast(list[JsonObject], payload["rules"])
    assert submitted[1] == {**payload, "rules": [rule for rule in rules if rule["type"] != "tag_name_pattern"]}
    assert payload_modes == [0o600, 0o600]
    assert not any(path.exists() for path in payload_paths)
```

Extend `test_unsupported_tag_metadata_classifier_rejects_uncorrelated_or_non_type_errors` with these exact negative values:

```python
        'gh: Validation Failed (HTTP 422)\n{"message":"Validation Failed","errors":["Invalid rule \'deletion\': "]}',
        'gh: Validation Failed (HTTP 422)\n{"message":"Validation Failed","errors":["Invalid field \'tag_name_pattern\': "]}',
        'gh: Validation Failed (HTTP 422)\n{"message":"Validation Failed","errors":["Invalid rule \'tag_name_pattern\': malformed regex"]}',
        'gh: Validation Failed (HTTP 422)\n{"message":"Validation Failed","errors":["Invalid rule", "\'tag_name_pattern\': "]}',
        '{"message":"Validation Failed","errors":["Invalid rule \'tag_name_pattern\': "]}',
```

- [ ] **Step 2: Run the regression and verify RED**

Run:

```bash
/Users/amattas/GitHub/aviato/.venv/bin/python -m pytest -q \
  tests/test_github.py::test_upsert_ruleset_reads_structured_unsupported_tag_error_from_stdout
```

Expected: the `object-entry` parameter passes and `live-string-entry` fails with `GitHubAPIError`; the current classifier ignores string entries.

- [ ] **Step 3: Implement the minimal whole-entry classifier**

In `_unsupported_tag_metadata_rule`, add the dedicated matcher beside `path_rejection`:

```python
    exact_string_rejection = re.compile(
        r'\s*invalid\s+rule\s+["\']tag_name_pattern["\']\s*:\s*',
        re.IGNORECASE,
    )
```

Then replace the top of the structured-error loop with:

```python
            for error in parsed["errors"]:
                if isinstance(error, str):
                    if exact_string_rejection.fullmatch(error):
                        return True
                    continue
                if not isinstance(error, dict):
                    continue
```

Do not alter the object-entry correlation or unstructured text matchers.

- [ ] **Step 4: Run focused verification and verify GREEN**

Run:

```bash
/Users/amattas/GitHub/aviato/.venv/bin/python -m pytest -q tests/test_github.py tests/test_rulesets.py
/Users/amattas/GitHub/aviato/.venv/bin/ruff check aviato/github.py tests/test_github.py
/Users/amattas/GitHub/aviato/.venv/bin/ruff format --check aviato/github.py tests/test_github.py
```

Expected: all focused tests pass, including both structured response parameters and all negative cases; Ruff exits 0.

- [ ] **Step 5: Commit the behavior change**

```bash
git add aviato/github.py tests/test_github.py
git commit -m "fix(rulesets): classify live string-list tag rejection"
```

---

### Task 2: Prove live convergence and reconcile durable records

**Files:**
- Modify: `tests/test_docs_index.py:145-218,335-402`
- Modify: `docs/specifications/modules/onboarding/flow.md:52-58`
- Modify: `docs/security/controls.md:52-59`
- Modify: `docs/requirements/traceability.md:97,108`
- Modify: `docs/requirements/modules/security/backlog.md:7-11`
- Modify: `docs/superpowers/plans/2026-07-12-repository-integrity-release-hardening.md:1-105`

**Interfaces:**
- Consumes: Task 1's exact string-entry classifier and the live ruleset IDs `17482301` (branch) and `17483804` (tag).
- Produces: successful degraded apply, exact live assertions, SEC-007 state `verified`, no completed SEC-007 backlog item, and a historically accurate consumed-authorization record.

- [ ] **Step 1: Dry-render and apply from the hotfix worktree**

Run the renderer first and inspect that both payloads contain `"bypass_actors": []`:

```bash
/Users/amattas/GitHub/aviato/.venv/bin/python -m aviato.cli render-rulesets --profile aviato-library
```

Then run the authorized operator apply:

```bash
/Users/amattas/GitHub/aviato/.venv/bin/python -m aviato.cli \
  apply-rulesets amattas/aviato --declaration .github/aviato.yaml --apply
```

Expected: exit 0; both rulesets report `Updated`; only the tag ruleset reports `DEGRADED` with `['tag_name_pattern']`. If the command fails, stop and do not update any durable state.

- [ ] **Step 2: Assert the exact live ruleset responses**

Run:

```bash
/Users/amattas/GitHub/aviato/.venv/bin/python - <<'PY'
from __future__ import annotations

import json
import subprocess

from aviato.rulesets import render_all_rulesets


def fetch(ruleset_id: int) -> dict[str, object]:
    result = subprocess.run(
        ["gh", "api", f"repos/amattas/aviato/rulesets/{ruleset_id}"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


desired = {payload["target"]: payload for payload in render_all_rulesets(extra_status_checks=["ci / Python CI"])}
branch = fetch(17482301)
tag = fetch(17483804)

assert branch["target"] == "branch"
assert branch["enforcement"] == "active"
assert branch["bypass_actors"] == []
assert branch["current_user_can_bypass"] == "never"
assert branch["conditions"] == desired["branch"]["conditions"]
branch_rules = {rule["type"]: rule.get("parameters", {}) for rule in branch["rules"]}
assert set(branch_rules) == {"deletion", "non_fast_forward", "pull_request", "required_status_checks", "code_scanning"}
assert branch_rules["pull_request"]["required_approving_review_count"] == 1
assert [item["context"] for item in branch_rules["required_status_checks"]["required_status_checks"]] == [
    "common-lint / Common lint",
    "security / Security baseline heartbeat",
    "ci / Python CI",
]
assert branch_rules["required_status_checks"]["strict_required_status_checks_policy"] is True
assert branch_rules["code_scanning"]["code_scanning_tools"] == [
    {"tool": "CodeQL", "security_alerts_threshold": "high_or_higher", "alerts_threshold": "none"}
]

assert tag["target"] == "tag"
assert tag["enforcement"] == "active"
assert tag["bypass_actors"] == []
assert tag["current_user_can_bypass"] == "never"
assert tag["conditions"] == desired["tag"]["conditions"]
assert [rule["type"] for rule in tag["rules"]] == ["deletion", "non_fast_forward"]

print("branch=17482301 zero-bypass exact-checks exact-codeql immutable")
print("tag=17483804 zero-bypass immutable metadata-pattern-only-degradation")
PY
```

Expected: both canonical summary lines print and the process exits 0.

- [ ] **Step 3: Write the post-rollout documentation guard and verify RED**

Replace `test_pr60_rollout_records_preserve_blocked_live_rollout_boundary` with:

```python
def test_pr60_rollout_records_preserve_verified_live_rollout_boundary() -> None:
    backlog = (ROOT / "docs/requirements/modules/security/backlog.md").read_text(encoding="utf-8")
    open_work = backlog.split("## Open", 1)[1].split("## Settled", 1)[0]
    assert "SEC-007" not in open_work

    sec007 = _matrix_rows()["SEC-007"]
    assert sec007[2] == "verified"
    assert "rules/17482301" in sec007[5]
    assert "rules/17483804" in sec007[5]

    controls = (ROOT / "docs/security/controls.md").read_text(encoding="utf-8")
    control = controls.split("## SEC-007", 1)[1].split("\n## ", 1)[0]
    normalized_control = " ".join(control.split())
    assert "Live readback on 2026-07-13 verified zero bypass actors" in normalized_control
    assert "exact CodeQL and required-check thresholds" in normalized_control

    onboarding = (ROOT / "docs/specifications/modules/onboarding/flow.md").read_text(encoding="utf-8")
    assert "Invalid rule 'tag_name_pattern':" in onboarding
    assert "one error entry at a time" in onboarding

    plan = (ROOT / "docs/superpowers/plans/2026-07-12-repository-integrity-release-hardening.md").read_text(
        encoding="utf-8"
    )
    normalized_plan = " ".join(plan.split())
    required_plan_evidence = {
        "Checkpoint 1 — completed",
        "a3e87ac00359309157fdeae153ebe29e03242a16",
        "gh pr merge 60 --repo amattas/aviato --merge --admin",
        "authorization was consumed",
        "not standing authorization",
        "zero bypass actors",
    }
    assert sorted(term for term in required_plan_evidence if term not in normalized_plan) == []
    assert "admin bypass is still present" not in normalized_plan
    assert "After PR #60 merges" not in normalized_plan
```

Also make these precise guard updates:

```python
# test_active_hardening_plan_matches_current_rollout_state required terms
"a3e87ac",
"authorization was consumed",
"zero bypass actors",

# test_high_risk_traceability_rows_use_precise_evidence
("SEC-007", ("rules/17482301", "rules/17483804")),

# Remove "SEC-007" from test_actionable_traceability_rows_link_to_an_owning_backlog.
```

Run:

```bash
/Users/amattas/GitHub/aviato/.venv/bin/python -m pytest -q tests/test_docs_index.py
```

Expected: failures show the current blocked SEC-007 row/backlog/control and stale active-plan state.

- [ ] **Step 4: Update the living specification and security records from the captured evidence**

In `docs/specifications/modules/onboarding/flow.md`, extend the 422 paragraph with this durable classifier contract:

```markdown
The correlated response may be a structured type-error object or the exact
whole-entry string `Invalid rule 'tag_name_pattern':` inside `errors`; string
matching examines one error entry at a time and never combines entries.
```

Remove the SEC-007 item from `docs/requirements/modules/security/backlog.md` and change the remaining Dependabot item to:

```markdown
- [live rollout] Enable Dependabot security updates and run `aviato doctor` now that ruleset convergence is verified. — trace: SEC-010
```

Change the THREAT-006 note and SEC-007 row in `docs/requirements/traceability.md` to:

```markdown
| THREAT-006 | [threat](../security/threat-model.md) | accepted | — | — | — | Mitigated by SEC-006 and verified SEC-007. |
| SEC-007 | [control](../security/controls.md) | verified | [onboarding](../specifications/modules/onboarding/flow.md) | [ruleset](../../aviato/library/rulesets/protect-default-branch.json) | [tests](../../tests/test_rulesets.py) · [classifier tests](../../tests/test_github.py) · [branch ruleset](https://github.com/amattas/aviato/rules/17482301) · [tag ruleset](https://github.com/amattas/aviato/rules/17483804) | Live readback on 2026-07-13 proved zero bypass actors, exact checks/CodeQL, and tag immutability with the documented metadata-pattern degradation. |
```

Replace the closing SEC-007 control text in `docs/security/controls.md` with:

```markdown
PR #60 merged as `a3e87ac00359309157fdeae153ebe29e03242a16`.
Live readback on 2026-07-13 verified zero bypass actors on the
[branch ruleset](https://github.com/amattas/aviato/rules/17482301) and
[tag ruleset](https://github.com/amattas/aviato/rules/17483804), exact CodeQL
and required-check thresholds, and branch/tag immutability; tag metadata-pattern
omission is the only degraded capability.
```

Update the active rollout plan date/status, current state, and Checkpoint 1 with these facts:

```markdown
- PR #60 merged as `a3e87ac00359309157fdeae153ebe29e03242a16` after the
  explicitly authorized one-time admin merge.
- Live branch ruleset readback proves zero bypass actors, the three exact
  required checks, exact CodeQL thresholds, and immutability.
- Live tag ruleset readback proves zero bypass actors and immutability; the
  unsupported metadata-pattern rule is the only degradation.

## Checkpoint 1 — completed

The user explicitly authorized this one-time command, which was run once:

```bash
gh pr merge 60 --repo amattas/aviato --merge --admin
```

That authorization was consumed and is not standing authorization for any
future bypass. The hotfix CLI completed the correlated tag-rule fallback, and
the exact live readback above closed SEC-007.
```

Keep Checkpoint 2 and later authorization boundaries unchanged. Remove SEC-007 from the remaining completion criteria because it is now completed.

- [ ] **Step 5: Run documentation guards and commit durable reconciliation**

Run:

```bash
/Users/amattas/GitHub/aviato/.venv/bin/python -m pytest -q tests/test_docs_index.py
/Users/amattas/GitHub/aviato/.venv/bin/ruff check tests/test_docs_index.py
/Users/amattas/GitHub/aviato/.venv/bin/ruff format --check tests/test_docs_index.py
git diff --check
```

Expected: all documentation tests pass and all formatting checks exit 0.

Commit:

```bash
git add tests/test_docs_index.py \
  docs/specifications/modules/onboarding/flow.md \
  docs/security/controls.md \
  docs/requirements/traceability.md \
  docs/requirements/modules/security/backlog.md \
  docs/superpowers/plans/2026-07-12-repository-integrity-release-hardening.md
git commit -m "docs: record verified ruleset convergence"
```

---

### Task 3: Prune temporary artifacts, verify, review, and publish

**Files:**
- Modify: `tests/test_docs_index.py:145-163`
- Delete: `docs/superpowers/specs/2026-07-13-tag-ruleset-string-422-design.md`
- Delete: `docs/superpowers/plans/2026-07-13-tag-ruleset-string-422.md`

**Interfaces:**
- Consumes: Task 1's code/tests and Task 2's live evidence/durable records.
- Produces: a final branch tip containing only durable code/tests/docs, strict-gate evidence, independent review, and one ready PR that awaits an external approval.

- [ ] **Step 1: Add the completed artifacts to the pruning guard and verify RED**

Add these paths to `completed` in `test_completed_superpowers_artifacts_are_pruned_but_active_plan_remains`:

```python
        "plans/2026-07-13-tag-ruleset-string-422.md",
        "specs/2026-07-13-tag-ruleset-string-422-design.md",
```

Run:

```bash
/Users/amattas/GitHub/aviato/.venv/bin/python -m pytest -q \
  tests/test_docs_index.py::test_completed_superpowers_artifacts_are_pruned_but_active_plan_remains
```

Expected: FAIL listing both still-present temporary artifacts.

- [ ] **Step 2: Delete only the completed hotfix design and plan, then verify GREEN**

Delete:

```text
docs/superpowers/specs/2026-07-13-tag-ruleset-string-422-design.md
docs/superpowers/plans/2026-07-13-tag-ruleset-string-422.md
```

Do not delete the still-active `2026-07-12-repository-integrity-release-hardening.md` plan.

Run:

```bash
/Users/amattas/GitHub/aviato/.venv/bin/python -m pytest -q tests/test_docs_index.py
git diff --check
```

Expected: all documentation tests pass and the diff check exits 0.

- [ ] **Step 3: Commit artifact pruning**

```bash
git add tests/test_docs_index.py docs/superpowers
git commit -m "docs: prune completed tag ruleset plans"
```

- [ ] **Step 4: Run the strict repository gate on the final branch tip**

Run:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
  AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh
```

Expected: every tool runs with no skip banner, all tests pass, wheel package data/runtime version verify, and strict mypy reports no issues.

- [ ] **Step 5: Obtain independent whole-branch review**

Generate/review the full diff from base `a3e87ac00359309157fdeae153ebe29e03242a16` through `HEAD`. The reviewer must separately verdict spec compliance and code quality, and specifically inspect:

```text
- exact whole-entry string matching and HTTP 422 gating
- no cross-entry correlation or broadened retry boundary
- degraded payload preservation and one-retry propagation
- live evidence before SEC-007 verification/backlog removal
- accurate consumed admin-authorization history
- completed Superpowers artifact pruning
```

Resolve every Critical or Important finding, rerun affected focused tests, and repeat the final review until clean. Rerun the strict gate after any code or test change.

- [ ] **Step 6: Push once, open one PR, and monitor CI**

```bash
git push -u origin codex/tag-ruleset-string-422
gh pr create --repo amattas/aviato \
  --base main \
  --head codex/tag-ruleset-string-422 \
  --title "fix(rulesets): handle live string-list tag rejection" \
  --body $'## Summary\n- recognize only the exact live string-list unsupported tag-rule 422\n- preserve fail-closed one-retry behavior and zero-bypass payloads\n- record exact live ruleset convergence and remove completed SEC-007 backlog work\n- prune completed Superpowers hotfix artifacts\n\n## Verification\n- focused GitHub/ruleset tests\n- strict local validation gate\n- live branch/tag ruleset readback\n- independent whole-branch review\n\n## Merge gate\nThe live ruleset reports `current_user_can_bypass: never`; this PR requires approval by a reviewer other than the author. Do not weaken protection or recreate a bypass.'
gh pr checks codex/tag-ruleset-string-422 --repo amattas/aviato --watch --interval 10
```

Expected: the PR is open, every required check reaches success, and merge remains blocked only on an external reviewer approval. Do not merge it in this task.
