# Solo-maintainer Ruleset Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Aviato's structurally impossible self-review gate without adding standing bypass authority or weakening any independent protection.

**Architecture:** The Library-wide policy remains one required approval. Aviato's own declaration deep-merges a zero-review exception into the composed default-branch settings, and the existing declaration-aware ruleset apply path renders that value. Living specifications and security records define the exception, accepted risk, reversal trigger, and live evidence; temporary Superpowers artifacts are pruned after those owners are current.

**Tech Stack:** YAML declaration, Python/Pytest governance tests, Markdown requirements/specification/security records, Aviato CLI, GitHub CLI/API.

## Global Constraints

- `.github/aviato.yaml` must declare `overrides.settings.default_branch.required_reviews: 0`.
- `aviato/library/policy.yml` and the baseline settings keep the default value `1`.
- The live branch ruleset keeps active enforcement, an empty bypass-actor list, pull-request enforcement, exact required checks, exact CodeQL thresholds, review-thread resolution, stale-review dismissal, deletion protection, and non-fast-forward protection.
- The live tag ruleset keeps active enforcement, an empty bypass-actor list, deletion protection, and non-fast-forward protection; only the documented `tag_name_pattern` degradation remains.
- The exception is valid only while no independent eligible reviewer exists and must be removed before or in the same settings change that adds one.
- PR #62 must merge through the normal merge path; do not use `--admin`.
- Push the branch once after local verification and live readback so GitHub CI runs only once for this amendment.
- Completed work does not enter a backlog; living docs and traceability own durable facts; completed Superpowers artifacts are pruned.

---

### Task 1: Encode, document, verify, and roll out the solo-maintainer exception

**Files:**
- Modify: `.github/aviato.yaml`
- Modify: `tests/test_docs_index.py`
- Modify: `tests/test_cli_apply_rulesets.py`
- Modify: `docs/specifications/modules/onboarding/flow.md`
- Modify: `docs/security/threat-model.md`
- Modify: `docs/security/controls.md`
- Modify: `docs/requirements/traceability.md`
- Modify: `docs/superpowers/plans/2026-07-12-repository-integrity-release-hardening.md`
- Delete after reconciliation: `docs/superpowers/specs/2026-07-13-solo-maintainer-ruleset-override-design.md`
- Delete after reconciliation: `docs/superpowers/plans/2026-07-13-solo-maintainer-ruleset-override.md`

**Interfaces:**
- Consumes: `Declaration.overrides`, `resolve_profile(..., overrides=...)`, and `aviato apply-rulesets --declaration`.
- Produces: resolved `default_branch.required_reviews == 0` for `amattas/aviato`, with unchanged rendered branch/tag ruleset fields outside that review-count leaf.

- [ ] **Step 1: Extend the existing SEC-007 governance test**

Rename `test_pr60_rollout_records_preserve_verified_live_rollout_boundary` to
`test_sec007_solo_maintainer_override_is_declared_and_documented`. Preserve its
existing backlog, traceability, and live-ruleset assertions, then add assertions
that:

```python
declaration = yaml.safe_load((ROOT / ".github/aviato.yaml").read_text(encoding="utf-8"))
assert declaration["overrides"]["settings"]["default_branch"] == {"required_reviews": 0}
```

The same test must require the onboarding specification to name
`required_reviews: 0`, the no-independent-reviewer precondition, retained
protections, and the reversal trigger; SEC-007 to distinguish the exception from
bypass permission; THREAT-006 to record the accepted lack of independent human
review; and the SEC-007 traceability row to link the declaration and PR #62.
Add one distinct CLI integration test that passes Aviato's actual declaration to
`apply-rulesets` and proves the resolved zero plus all three checks reach the
ruleset apply boundary.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
  python -m pytest \
  tests/test_docs_index.py::test_sec007_solo_maintainer_override_is_declared_and_documented -q
```

Expected: FAIL because `.github/aviato.yaml` has no `overrides` key and the
living documents do not yet define the solo-maintainer contract.

- [ ] **Step 3: Add the minimal declaration and living-document changes**

Add this exact declaration block without changing the profile default:

```yaml
overrides:
  settings:
    default_branch:
      required_reviews: 0
```

Update the onboarding specification, THREAT-006, SEC-007, SEC-007 traceability
row, and active rollout plan with the approved design. Do not add a completed
backlog item. Keep `SEC-007` in state `verified` only after the live readback in
Step 7 proves the changed approval count and retained controls.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
  python -m pytest tests/test_docs_index.py tests/test_rulesets.py \
  tests/test_cli_apply_rulesets.py tests/core/test_composition.py -q
```

Expected: all selected tests PASS, including the extended SEC-007 governance
test and existing zero-approval propagation tests.

- [ ] **Step 5: Reconcile durable decisions**

Record the rejected standing-bypass and recurring-admin-merge alternatives in
the security backlog's settled decisions. Preserve both existing SEC-010 open
items unchanged. Defer pruning until the live evidence is reconciled.

- [ ] **Step 6: Run independent review and the focused pre-live gate**

Have a fresh reviewer inspect the complete amendment for scope, security, test
non-redundancy, documentation ownership, and exact retained ruleset fields.
Resolve any Critical or Important finding. The focused suite and exact render
from Step 4 are the pre-live safety gate; the strict full gate runs after the
final live evidence update so it is not repeated on stale inputs.

- [ ] **Step 7: Apply from the declaration and verify exact live state**

Run:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
  python -m aviato.cli apply-rulesets amattas/aviato \
  --declaration .github/aviato.yaml --apply
```

Read back rulesets `17482301` and `17483804`. Assert the branch approval count
is `0`; both bypass lists are empty and enforcement is `active`; branch
conditions, required checks, CodeQL thresholds, thread resolution, stale-review
dismissal, deletion, and non-fast-forward rules match the pre-change snapshot;
and the tag ruleset remains immutable with no additional degradation.

- [ ] **Step 8: Reconcile evidence, prune, verify, commit, push once, and merge normally**

Update SEC-007 and the active hardening plan with the exact live zero-review
readback. Add both temporary artifact paths to the completed-artifact guard,
delete this plan and its design, and confirm every durable statement is present
in the specification, threat model, control, traceability matrix, settled
decision, or active rollout plan. Run a fresh final review and the strict gate:

```bash
PATH="/Users/amattas/GitHub/aviato/.venv/bin:$PATH" \
  AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh
```

Expected: every tool runs, no skips are reported, and the full suite passes.

Commit the final amendment, push `codex/tag-ruleset-string-422` once, wait for
all PR #62 checks, and confirm `reviewDecision` no longer blocks the PR. Merge
without administrator bypass:

```bash
gh pr merge 62 --repo amattas/aviato --merge
```

Expected: the merge succeeds through the ordinary protected-branch path. Fetch
and fast-forward the primary checkout's `main`, verify the merge commit and
clean worktree state, and remove the merged feature worktree/branch when safe.
