# Starter Documentation Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship reusable documentation-governance and test-consolidation starter assets, adopt the same living documentation model in Aviato, retire completed backlogs/plans, and remove Aviato's unused self-docs website.

**Architecture:** Four canonical skill masters live in `starter/skills/`; `starter/CLAUDE.md` and `starter/AGENTS.md` share one byte-identical marked governance block while retaining tool-specific introductions. Consumer skills are replaced atomically after drift review, agent files merge only the managed block, and living docs/matrices remain seed-once. Aviato's numbered normative sections keep their headings and § index while whole behavior-heavy documents move from `docs/requirements/` to parallel `docs/specifications/`; security posture moves into a threat model, controls inventory, and architecture view.

**Tech Stack:** Markdown, Python 3.12, pytest, PyYAML, Git, repository validation scripts.

**Spec:** `docs/superpowers/specs/2026-07-12-starter-documentation-governance-design.md`

## Global Constraints

- Use `AGENTS.md`, not singular `AGENT.md`, for Codex repository instructions.
- Keep canonical skill masters at `starter/skills/<name>/`; consumers copy them to `.claude/skills/<name>/`.
- Replace managed skills atomically only after checking local drift; preserve every non-managed skill.
- Merge only the marked governance block in existing agent files; preserve project-specific prose outside it.
- Seed `docs/requirements/traceability.md` and living docs once; never reset active content from starter templates.
- Requirements state what and why; specifications state precise testable behavior; architecture states current structure.
- Security traceability follows `THREAT-* -> SEC-* -> specification -> control/code -> verification`.
- Remove completed work from backlog `Open`; keep only unresolved work and settled decisions.
- Promote durable content before pruning dated Superpowers artifacts; keep the active repository-hardening plan until its live rollout is complete.
- Preserve every existing § heading and code citation through `docs/requirements/README.md`.
- Delete Aviato's own unused `website/` and self-docs workflow, but retain the consumer docs-site capability and starter scaffold.
- Favor coherent local commits and one eventual PR; do not push until the full local gate passes.
- TDD rigor does not imply redundant test volume; extend or parameterize existing tests where they exercise one behavior.

---

### Task 1: Lock the starter governance contract with failing tests

**Files:**
- Create: `tests/test_starter_governance.py`
- Test: `tests/test_starter_governance.py`

**Interfaces:**
- Consumes: design paths and managed markers.
- Produces: deterministic contract tests used by Tasks 2–3.

- [ ] **Step 1: Write the failing structural tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "starter"
SKILLS = ("docs-structure", "traceability", "docs-reconciliation", "test-consolidation")
START = "<!-- aviato:documentation-governance:start -->"
END = "<!-- aviato:documentation-governance:end -->"


def _managed_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.count(START) == text.count(END) == 1
    return START + text.split(START, 1)[1].split(END, 1)[0] + END


def test_starter_governance_assets_exist() -> None:
    expected = [STARTER / name for name in ("CLAUDE.md", "AGENTS.md")]
    expected += [STARTER / "skills" / name / "SKILL.md" for name in SKILLS]
    expected += [STARTER / "docs/requirements/traceability.md"]
    assert [path.relative_to(ROOT) for path in expected if not path.is_file()] == []


def test_agent_templates_share_the_exact_managed_block() -> None:
    assert _managed_block(STARTER / "CLAUDE.md") == _managed_block(STARTER / "AGENTS.md")


def test_managed_block_names_skills_completion_and_cost_rules() -> None:
    block = _managed_block(STARTER / "AGENTS.md")
    required = {
        *SKILLS,
        "docs/requirements/traceability.md",
        "completed work",
        "parameterized",
        "CI",
        "rework",
    }
    assert sorted(term for term in required if term not in block) == []


def test_traceability_template_has_canonical_schema_and_states() -> None:
    text = (STARTER / "docs/requirements/traceability.md").read_text(encoding="utf-8")
    for column in (
        "ID", "Source", "State", "Specification", "Implementation evidence",
        "Verification evidence", "Notes",
    ):
        assert f"| {column} " in text
    for state in ("proposed", "accepted", "implemented", "verified", "blocked", "retired"):
        assert f"`{state}`" in text
```

- [ ] **Step 2: Run RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_starter_governance.py`

Expected: failures list missing `starter/CLAUDE.md`, `starter/AGENTS.md`, matrix, and three new skill masters.

- [ ] **Step 3: Commit the verified-red contract**

```bash
git add tests/test_starter_governance.py
git commit -m "test: define starter documentation governance contract"
```

---

### Task 2: Author and validate each repo-local skill

**Files:**
- Modify: `starter/skills/docs-structure/SKILL.md`
- Create: `starter/skills/traceability/SKILL.md`
- Create: `starter/skills/docs-reconciliation/SKILL.md`
- Create: `starter/skills/test-consolidation/SKILL.md`
- Source: `/Users/amattas/.claude/skills/test-consolidation/SKILL.md`
- Test: `tests/test_starter_governance.py`

**Interfaces:**
- Consumes: the approved design, existing docs-structure skill, and global test-consolidation skill.
- Produces: four concise, self-contained starter skill masters referenced by agent templates.

- [ ] **Step 1: Run a RED pressure scenario for `docs-structure` without exposing its skill**

Use a fresh subagent with only this scenario: a repository mixes requirements, API behavior, architectural decisions, threats, completed backlog entries, and old plans; ask it to propose the target tree. Record whether it conflates requirements/specifications, leaves security implicit, or treats plans as records. This is the required writing-skills baseline; do not edit the skill first.

- [ ] **Step 2: Update `docs-structure` minimally and run GREEN**

Add the approved `docs/specifications/`, `docs/security/`, traceability, ownership, backlog, and Superpowers-lifecycle rules. Re-run the same fresh-context scenario with the skill path supplied; require correct classification and promotion-before-pruning.

- [ ] **Step 3: Run RED/GREEN for `traceability`**

RED prompt: provide a fixture with a missing requirement row, duplicate ID, `verified` row without evidence, unresolved evidence link, and an external gate falsely described as passed. Record baseline misses. Initialize with the skill-creator script under `starter/skills`, replace generated placeholders with a concise workflow, and re-run with the skill. GREEN requires all five defects reported and no invented evidence.

- [ ] **Step 4: Run RED/GREEN for `docs-reconciliation`**

RED prompt: provide living docs plus an old plan containing one durable threat, one implemented backlog item, and one unresolved item. Record any premature deletion or history retention. Initialize and write the skill. GREEN requires promotion of the threat, removal of completed backlog work, preservation of unresolved work in its owning backlog, traceability update, and pruning only after verification.

- [ ] **Step 5: Validate the existing `test-consolidation` skill before copying it**

RED prompt without the skill: ask to reduce a duplicated green suite under deadline pressure where two similarly named tests cover different authorization states. Record unsafe deletion or mega-test behavior. GREEN prompt supplies `/Users/amattas/.claude/skills/test-consolidation/SKILL.md` and must preserve distinct behavior, parameterize literal variants only, request approval before destructive reduction, and report baseline/final evidence. Then copy the already-authored skill verbatim to `starter/skills/test-consolidation/SKILL.md`.

- [ ] **Step 6: Validate every skill folder**

Run:

```bash
/Users/amattas/.codex/skills/.system/skill-creator/scripts/quick_validate.py starter/skills/docs-structure
/Users/amattas/.codex/skills/.system/skill-creator/scripts/quick_validate.py starter/skills/traceability
/Users/amattas/.codex/skills/.system/skill-creator/scripts/quick_validate.py starter/skills/docs-reconciliation
/Users/amattas/.codex/skills/.system/skill-creator/scripts/quick_validate.py starter/skills/test-consolidation
```

Expected: `Skill is valid!` four times. Also run `wc -w starter/skills/*/SKILL.md`; keep each focused and below 500 words unless the imported test skill's safety rules require its existing length.

- [ ] **Step 7: Run the affected test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_starter_governance.py`

Expected: only the still-missing agent templates/matrix assertions fail; skill paths pass.

- [ ] **Step 8: Commit the independently validated skills**

```bash
git add starter/skills tests/test_starter_governance.py
git commit -m "feat(starter): add documentation governance skills"
```

---

### Task 3: Add merge-safe agent templates and the seed matrix

**Files:**
- Create: `starter/CLAUDE.md`
- Create: `starter/AGENTS.md`
- Create: `starter/docs/requirements/traceability.md`
- Modify: `starter/README.md`
- Modify: `docs/requirements/modules/starter-kit/conventions.md`
- Test: `tests/test_starter_governance.py`

**Interfaces:**
- Consumes: four skill names and the canonical matrix schema.
- Produces: copy-ready templates with one shared managed block and documented update semantics.

- [ ] **Step 1: Extend RED tests for lifecycle documentation**

```python
def test_starter_readme_documents_governance_copy_and_update_semantics() -> None:
    text = (STARTER / "README.md").read_text(encoding="utf-8")
    for term in (
        "starter/CLAUDE.md", "starter/AGENTS.md", ".claude/skills/",
        "replace", "managed block", "seed-once", "local modifications",
    ):
        assert term in text
```

Run the single test and confirm it fails because the README lacks the lifecycle contract.

- [ ] **Step 2: Create the templates**

Give each file a short tool-specific preface, then the same marked block. The block must require reading all four repo-local skills, reconciling completed backlog work and traceability before completion, promoting durable plan content before pruning, distinct-behavior/parameterized tests, local verification before publishing, and coherent batching without weakening gates.

- [ ] **Step 3: Create the seed matrix**

Create the seven-column table, list allowed states, state the evidence transition rules, include one clearly labeled illustrative row that consumers must replace, and state that later updates merge content rather than replacing the file.

- [ ] **Step 4: Document adoption and update behavior**

Add an exact copy table to `starter/README.md`. State: managed skills are whole-directory replacements after drift review; unknown skills are preserved; locally modified managed skills require an operator decision; agent files merge only the marked block; matrix/living docs are seed-once. Add the same normative rules to starter-kit requirements.

- [ ] **Step 5: Run GREEN**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_starter_governance.py`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add starter docs/requirements/modules/starter-kit/conventions.md tests/test_starter_governance.py
git commit -m "feat(starter): add merge-safe agent guidance"
```

---

### Task 4: Reclassify Aviato's living requirements and specifications

**Files:**
- Create: `docs/specifications/README.md`
- Move: `docs/requirements/core/consumer-contract.md` → `docs/specifications/core/consumer-contract.md`
- Move: `docs/requirements/modules/onboarding/flow.md` → `docs/specifications/modules/onboarding/flow.md`
- Move: `docs/requirements/modules/onboarding/bootstrap.md` → `docs/specifications/modules/onboarding/bootstrap.md`
- Move: `docs/requirements/modules/scaffolding/sync.md` → `docs/specifications/modules/scaffolding/sync.md`
- Move: `docs/requirements/modules/drift/file-drift.md` → `docs/specifications/modules/drift/file-drift.md`
- Move: `docs/requirements/modules/drift/settings-drift.md` → `docs/specifications/modules/drift/settings-drift.md`
- Move: `docs/requirements/modules/fleet/diagnosis.md` → `docs/specifications/modules/fleet/diagnosis.md`
- Move: `docs/requirements/modules/fleet/scan.md` → `docs/specifications/modules/fleet/scan.md`
- Move: `docs/requirements/modules/reconcile/flow.md` → `docs/specifications/modules/reconcile/flow.md`
- Move: `docs/requirements/modules/reconcile/consent.md` → `docs/specifications/modules/reconcile/consent.md`
- Move: `docs/requirements/modules/versioning/release.md` → `docs/specifications/modules/versioning/release.md`
- Move: `docs/requirements/modules/versioning/repin.md` → `docs/specifications/modules/versioning/repin.md`
- Move: `docs/requirements/modules/offboarding/flow.md` → `docs/specifications/modules/offboarding/flow.md`
- Move: `docs/requirements/modules/security/scanning.md` → `docs/specifications/modules/security/scanning.md`
- Move: `docs/requirements/modules/security/supply-chain.md` → `docs/specifications/modules/security/supply-chain.md`
- Move: `docs/requirements/modules/languages/python/requirements.md` → `docs/specifications/modules/languages/python/requirements.md`
- Move: `docs/requirements/modules/languages/node/requirements.md` → `docs/specifications/modules/languages/node/requirements.md`
- Move: `docs/requirements/modules/languages/swift/requirements.md` → `docs/specifications/modules/languages/swift/requirements.md`
- Move: `docs/requirements/modules/deployment/pypi/requirements.md` → `docs/specifications/modules/deployment/pypi/requirements.md`
- Move: `docs/requirements/modules/deployment/ghcr/requirements.md` → `docs/specifications/modules/deployment/ghcr/requirements.md`
- Move: `docs/requirements/modules/deployment/docs-site/requirements.md` → `docs/specifications/modules/deployment/docs-site/requirements.md`
- Move: `docs/requirements/modules/deployment/apple/requirements.md` → `docs/specifications/modules/deployment/apple/requirements.md`
- Modify: `docs/requirements/README.md`
- Modify: `REQUIREMENTS.md`
- Modify: `ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `tests/test_docs_index.py`

**Interfaces:**
- Consumes: existing stable § headings and the requirements index parser.
- Produces: parallel living requirements/specifications without breaking any code citation.

- [ ] **Step 1: Write RED classification tests**

Parameterize one test over every document to move. Assert the old path is absent, the new path exists, and the § index points to the new relative path. Add assertions that `docs/specifications/README.md` defines the requirements/specifications boundary and that every indexed path resolves even when it begins `../specifications/`.

- [ ] **Step 2: Run RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_docs_index.py`

Expected: classification tests fail on missing `docs/specifications/` paths.

- [ ] **Step 3: Move whole documents and update the index**

Use `git mv` per file. Preserve all § headings and prose. Update only the index's File column and navigation prose; paths from `docs/requirements/README.md` use `../specifications/...`. Do not split a numbered subsection or renumber any heading.

- [ ] **Step 4: Update entry points**

Make the root stubs, README, and root `CLAUDE.md` describe requirements as outcomes/constraints, specifications as exact behavior, architecture as current structure, and security docs as threat/control records. Keep `docs/requirements/README.md` the citation resolver.

- [ ] **Step 5: Run GREEN**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_docs_index.py`

Expected: all index, citation, and classification tests pass.

- [ ] **Step 6: Commit**

```bash
git add REQUIREMENTS.md ARCHITECTURE.md README.md CLAUDE.md docs/requirements docs/specifications tests/test_docs_index.py
git commit -m "docs: separate requirements from specifications"
```

---

### Task 5: Add Aviato security records and complete traceability

**Files:**
- Create: `docs/security/threat-model.md`
- Create: `docs/security/controls.md`
- Create: `docs/architecture/security.md`
- Create: `docs/requirements/traceability.md`
- Modify: `SECURITY.md`
- Modify: `docs/architecture/overview.md`
- Modify: `tests/test_docs_index.py`

**Interfaces:**
- Consumes: public security policy, §2.3/§2.7/§2.12/§2.13, security specifications, workflows, rulesets, and tests.
- Produces: threat IDs, security requirement IDs, control inventory, architecture view, and evidence-backed canonical traceability.

- [ ] **Step 1: Write RED traceability/security tests**

Parse the requirements § index, threat headings, and matrix table. Assert every indexed requirement has exactly one matrix row, every `THREAT-*` has a row, IDs are unique, allowed states are used, source/specification links resolve, and `implemented`/`verified` rows have the required evidence fields. Assert the three security documents exist and cross-link threats, requirements, controls, and verification.

- [ ] **Step 2: Run RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_docs_index.py`

Expected: failures identify the missing matrix and security documents.

- [ ] **Step 3: Build the threat model and control inventory**

Promote durable content from `SECURITY.md` and completed plans: consumer-code execution, reusable-workflow blast radius, credential scopes, untrusted PR/workflow-run boundaries, supply-chain inputs, artifact byte identity, ruleset/API degradation, release ref binding, and docs deployment privileges. Assign stable `THREAT-*` IDs, mitigations, residual risks, and verification references. Map security outcomes to stable `SEC-*` IDs in controls and traceability.

- [ ] **Step 4: Create the architecture security view**

Document assets, trust boundaries, privileged jobs, operator/platform/consumer responsibilities, and the threat→control flow using Mermaid. Do not duplicate the threat narratives.

- [ ] **Step 5: Populate traceability**

Use one row for every § index key plus every threat/security ID. State only evidence proven by repository files/tests. Mark external live gates accurately as blocked or outstanding rather than verified. Link specifications using their new paths and implementation/verification evidence using current code and tests.

- [ ] **Step 6: Reduce `SECURITY.md` to public policy plus posture navigation**

Retain reporting channels, supported-version policy, and a concise posture summary. Link detailed threats and controls; remove duplicated internal control prose only after it exists in living docs.

- [ ] **Step 7: Run GREEN and commit**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_docs_index.py`

Expected: all documentation integrity tests pass.

```bash
git add SECURITY.md docs/security docs/architecture docs/requirements/traceability.md tests/test_docs_index.py
git commit -m "docs: add security and traceability records"
```

---

### Task 6: Reconcile backlogs and prune completed dated artifacts

**Files:**
- Modify: every `docs/requirements/**/backlog.md` containing `## Resolved by ...`
- Delete: completed `docs/superpowers/plans/2026-05-21-agnostic-core-engine.md`
- Delete: completed `docs/superpowers/plans/2026-05-29-actionpins-zizmor-migration.md`
- Delete: completed `docs/superpowers/plans/2026-07-11-docs-restructure.md`
- Delete: completed `docs/superpowers/plans/2026-07-11-zensical-docs.md`
- Delete: `docs/superpowers/specs/2026-05-29-actionpins-zizmor-migration-design.md`
- Delete: `docs/superpowers/specs/2026-07-11-docs-restructure-design.md`
- Delete: `docs/superpowers/specs/2026-07-11-zensical-docs-design.md`
- Delete after promotion: `docs/superpowers/specs/2026-07-12-starter-documentation-governance-design.md`
- Delete after promotion: `docs/superpowers/plans/2026-07-12-starter-documentation-governance.md`
- Preserve: `docs/superpowers/plans/2026-07-12-repository-integrity-release-hardening.md` until the live hardening rollout finishes
- Modify: `tests/test_docs_index.py`

**Interfaces:**
- Consumes: completed-work evidence and the traceability/security/specification records from Tasks 4–5.
- Produces: backlogs containing only open work and settled decisions; dated artifacts only for active work.

- [ ] **Step 1: Write RED cleanup tests**

Assert no backlog contains a `Resolved`/`Completed` section, no completed 2026-05/07-11 artifact remains, every backlog has `## Open` and `## Settled — do not reopen`, and the active hardening plan still exists.

- [ ] **Step 2: Run RED**

Expected: failures list resolved backlog sections and completed dated artifacts.

- [ ] **Step 3: Promote and prune using `docs-reconciliation`**

Audit every deleted artifact for durable requirements, specifications, architectural decisions, threats, accepted risks, and open work. Confirm each has a living destination and traceability entry before deletion. Remove resolved sections entirely; keep unresolved mike-native versioning work in the docs-site backlog and keep all settled decisions.

- [ ] **Step 4: Run GREEN and commit**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_docs_index.py`

Expected: cleanup and citation tests pass.

```bash
git add docs tests/test_docs_index.py
git commit -m "docs: prune completed planning records"
```

---

### Task 7: Retire Aviato's unused self-docs site without removing consumer docs support

**Files:**
- Delete: `website/`
- Delete: `.github/workflows/aviato-docs.yml`
- Delete: `.github/aviato.seed.json`
- Modify: `.github/aviato.yaml`
- Modify: `.gitignore`
- Modify: `scripts/sync-docs-toolchain-pins.py`
- Modify: `aviato/validation.py`
- Modify: `tests/test_docs_toolchain_parity.py`
- Modify: `tests/test_workflow_guards.py`
- Modify: `tests/test_validation_negative.py`
- Modify: `docs/architecture/infrastructure.md`
- Modify: `docs/requirements/traceability.md`

**Interfaces:**
- Consumes: consumer docs-site masters under `starter/docs-site/` and `aviato/library/scaffold/`.
- Produces: a Library declaration with `docs: false`, no self-docs deployment surface, and unchanged consumer docs capability.

- [ ] **Step 1: Update tests first**

Change docs-pin expectations from three outputs to exactly two:

```python
assert list(outputs) == [
    Path("starter/docs-site/requirements.txt"),
    Path("aviato/library/scaffold/files/docs-requirements.txt.txt"),
]
```

Add assertions that `website/`, `.github/workflows/aviato-docs.yml`, and `.github/aviato.seed.json` are absent, `.github/aviato.yaml` has `docs: false`, and consumer docs scaffold/workflow tests remain present. Move tests that inspect the Library's generated docs caller to the authoritative scaffold caller bodies instead of deleting their security assertions.

- [ ] **Step 2: Run RED**

Run the affected tests and confirm failures arise from the still-present self-docs outputs/declaration.

- [ ] **Step 3: Remove the self-docs surface**

Delete the authorized files/tree. Set `docs: false`, remove the now-unused `serve-pages` variable, remove self-site ignore rules, drop the website output from the pin synchronizer and validation parity list, and remove Library-only workflow-name parity checks. Preserve reusable docs workflows, profile composition, starter docs scaffold, and consumer tests.

- [ ] **Step 4: Update living records**

Record that Aviato provides consumer docs deployment but does not publish a self-docs site. Update architecture and traceability evidence; do not describe deletion of `website/` as retirement of the Zensical consumer capability.

- [ ] **Step 5: Run GREEN**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_docs_toolchain_parity.py tests/test_workflow_guards.py \
  tests/test_validation_negative.py tests/test_starter_governance.py tests/test_docs_index.py
```

Expected: all affected tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A website .github .gitignore scripts aviato tests docs
git commit -m "chore(docs): retire unused Aviato self-site"
```

---

### Task 8: Full verification and final reconciliation

**Files:**
- Modify if evidence requires correction: `docs/requirements/traceability.md`
- Modify if an active item changed: owning `backlog.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: CI-parity evidence for one reviewable, unpushed branch.

- [ ] **Step 1: Validate skill packages**

Run `quick_validate.py` for all four skills and confirm all pass.

- [ ] **Step 2: Run focused documentation tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_starter_governance.py tests/test_docs_index.py tests/test_docs_toolchain_parity.py`

Expected: all pass with no warnings.

- [ ] **Step 3: Run the full strict local gate**

Run: `env PATH="$PWD/.venv/bin:$PATH" AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh > /tmp/aviato-governance-validate.log 2>&1`

Expected: exit 0. On failure, inspect only errors/warnings and use systematic debugging before editing.

- [ ] **Step 4: Run final documentation reconciliation**

Use the new traceability and docs-reconciliation skills against the final tree. Confirm no completed item remains in backlog Open, every traceability state matches evidence, every durable deleted-plan fact has a living home, the active hardening plan remains, and `rg -n "website/requirements.txt|\.github/workflows/aviato-docs.yml" --glob '!docs/superpowers/**' .` reports no Library self-site dependency.

- [ ] **Step 5: Inspect the final diff and status**

Run: `git diff origin/main...HEAD --check`, `git status --short`, and a path/stat summary. Confirm no unrelated files or user artifacts are included.

- [ ] **Step 6: Commit any evidence-only corrections**

```bash
git add docs/requirements/traceability.md docs/requirements/**/backlog.md
git commit -m "docs: reconcile governance evidence"
```

Skip the commit if there are no corrections. Do not push until the user authorizes publication after reviewing the verified result.
