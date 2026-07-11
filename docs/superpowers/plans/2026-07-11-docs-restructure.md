# Docs Restructure + docs-structure Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `REQUIREMENTS.md` and `ARCHITECTURE.md` into a per-module `docs/` tree with a guarded § index, seed per-module backlogs from the findings docs, and ship a reusable `docs-structure` skill in the starter kit.

**Architecture:** A one-off Python script performs the split deterministically (segment the monoliths at headings, route each §-numbered block to its target file, auto-generate the § → file index). A new stdlib-only pytest guards the invariant that every § cited in `aviato/**/*.py` resolves through the index. Backlog seeding is a manual triage pass with per-item verification hints.

**Tech Stack:** Python 3.12 stdlib, pytest (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` compatible), git.

**Spec:** `docs/superpowers/specs/2026-07-11-docs-restructure-design.md`

## Global Constraints

- **§ integrity:** original §-numbered headings move verbatim; never split one `§x.y` across files; never renumber. 644 docstring citations must keep resolving.
- **Mechanical split:** prose moves verbatim. No rewriting. (Finding: all 23 REQUIREMENTS.md fences are already Mermaid; ARCHITECTURE.md's 2 fences are code examples — zero conversion work, verify preservation only.)
- **No engine-code changes** beyond the new guard test.
- Work happens on the existing `docs/restructure` branch. Commit after each task; **do not push**.
- Every commit message ends with:
  `Claude-Session: https://claude.ai/code/session_015oBvsuGofC7reacf66rWjV`
- Lint rules for new Python: ruff + black, line length 120, py312. Tests must not import third-party pytest plugins.
- Run tests as: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q` (project conda env, not base).
- The scratchpad for the one-off script: `/private/tmp/claude-501/-Users-amattas-GitHub-aviato/97cae9a4-e30b-45c8-9ece-ebd1c0c78478/scratchpad` (the script is NOT committed; the guard test verifies the result).

---

### Task 1: Guard test (red)

**Files:**
- Test: `tests/test_docs_index.py`

**Interfaces:**
- Produces: the invariant later tasks must satisfy — `docs/requirements/README.md` must contain a markdown table whose rows look like `| §5.2 | Repository onboarding (…) | modules/onboarding/flow.md |` with paths relative to `docs/requirements/`.

- [ ] **Step 1: Write the failing test**

```python
"""Guard: every § requirements citation in engine code resolves through the docs index.

The 2026-07-11 docs restructure split REQUIREMENTS.md into docs/requirements/**
with § numbering preserved verbatim. docs/requirements/README.md carries the
§ -> file index. Every §N[.N] cited in aviato/**/*.py must resolve
(longest-prefix) to an indexed file that still contains the cited number.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "requirements" / "README.md"
CODE_ROOT = ROOT / "aviato"

# Citations whose literal number never appeared in REQUIREMENTS.md:
# §9.2 cites item 2 of §9's list (the items are unnumbered prose in the
# source). Prefix resolution to §9 is the strongest possible check for it.
LITERAL_ABSENT_OK = {"9.2"}

REF_RE = re.compile(r"§\s*([0-9][0-9a-z.]*)")
ROW_RE = re.compile(r"^\|\s*§([0-9][0-9a-z.]*)\s*\|[^|]*\|\s*([^|]+?)\s*\|\s*$")


def _index() -> dict[str, Path]:
    rows: dict[str, Path] = {}
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        match = ROW_RE.match(line)
        if match:
            rows[match.group(1)] = INDEX.parent / match.group(2)
    return rows


def _cited() -> set[str]:
    refs: set[str] = set()
    for source in CODE_ROOT.rglob("*.py"):
        for match in REF_RE.finditer(source.read_text(encoding="utf-8")):
            refs.add(match.group(1).rstrip("."))
    return refs


def _resolve(ref: str, index: dict[str, Path]) -> Path | None:
    key = ref
    while True:
        if key in index:
            return index[key]
        if "." not in key:
            return None
        key = key.rsplit(".", 1)[0]


def test_index_rows_exist_and_contain_their_heading() -> None:
    index = _index()
    assert index, f"no § rows parsed from {INDEX}"
    for key, path in index.items():
        assert path.is_file(), f"§{key}: indexed file missing: {path}"
        heading = re.compile(rf"^#{{1,3}} {re.escape(key)}[. ]", re.MULTILINE)
        assert heading.search(path.read_text(encoding="utf-8")), f"§{key}: heading not found in {path}"


def test_every_code_citation_resolves_through_the_index() -> None:
    index = _index()
    cited = _cited()
    assert cited, "no § citations found in aviato/**/*.py"
    unresolved: list[str] = []
    literal_missing: list[str] = []
    for ref in sorted(cited):
        target = _resolve(ref, index)
        if target is None or not target.is_file():
            unresolved.append(ref)
        elif ref not in LITERAL_ABSENT_OK and ref not in target.read_text(encoding="utf-8"):
            literal_missing.append(f"§{ref} -> {target.relative_to(ROOT)}")
    assert not unresolved, f"citations with no index entry: {unresolved}"
    assert not literal_missing, f"cited numbers absent from their resolved file: {literal_missing}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_docs_index.py -q`
Expected: 2 FAILED — `FileNotFoundError` (or empty-index assert) because `docs/requirements/README.md` does not exist.

No commit yet — the suite must stay green per commit; this test is committed with Task 2's split.

---

### Task 2: Split REQUIREMENTS.md → docs/requirements/** (green)

**Files:**
- Create: `<scratchpad>/split_docs.py` (one-off, NOT committed)
- Create: `docs/requirements/README.md` + 32 split files (mapping below)
- Modify: `REQUIREMENTS.md` (→ pointer stub)
- Test: `tests/test_docs_index.py` (from Task 1)

**Interfaces:**
- Consumes: Task 1's index-table format.
- Produces: the `docs/requirements/` tree all later tasks reference. Backlog files are NOT created here (Task 5).

- [ ] **Step 1: Write the split script to the scratchpad**

```python
#!/usr/bin/env python3
"""One-off: split REQUIREMENTS.md + ARCHITECTURE.md into docs/ (2026-07-11 design)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path("/Users/amattas/GitHub/aviato")

# ---------------- REQUIREMENTS.md ----------------
# target file (relative to docs/requirements/) -> ordered § block keys
MAPPING: dict[str, list[str]] = {
    "core/purpose.md": ["1"],
    "core/principles.md": ["2"] + [f"2.{i}" for i in range(1, 15)],
    "core/structure.md": ["3", "3.1", "3.2", "3.3", "3.4"],
    "core/modularity.md": ["4", "4.1", "4.2", "4.3", "5", "5.1"],
    "core/consumer-contract.md": ["6"] + [f"6.{i}" for i in range(1, 7)],
    "core/state-and-failures.md": ["7", "8"],
    "core/definition-of-done.md": ["9", "9b"],
    "modules/README.md": ["10", "10.1", "10.3", "15", "16", "17"],
    "modules/onboarding/flow.md": ["5.2"],
    "modules/onboarding/bootstrap.md": ["5.10"],
    "modules/scaffolding/sync.md": ["5.3"],
    "modules/drift/file-drift.md": ["5.5"],
    "modules/drift/settings-drift.md": ["5.6"],
    "modules/reconcile/flow.md": ["5.7"],
    "modules/reconcile/consent.md": ["5.8"],
    "modules/versioning/release.md": ["5.9"],
    "modules/versioning/repin.md": ["5.12"],
    "modules/fleet/diagnosis.md": ["5.4"],
    "modules/fleet/scan.md": ["5.11"],
    "modules/offboarding/flow.md": ["5.13"],
    "modules/security/scanning.md": ["5.14"],
    "modules/security/supply-chain.md": ["11.3"],
    "modules/languages/README.md": ["12", "10.2"],
    "modules/languages/python/requirements.md": ["12.1"],
    "modules/languages/node/requirements.md": ["12.2"],
    "modules/languages/swift/requirements.md": ["12.3"],
    "modules/deployment/README.md": ["11", "11.1", "11.2", "11.5", "11.6", "11.7", "13", "13.5", "14"],
    "modules/deployment/pypi/requirements.md": ["13.1"],
    "modules/deployment/ghcr/requirements.md": ["13.2"],
    "modules/deployment/docs-site/requirements.md": ["13.3"],
    "modules/deployment/apple/requirements.md": ["13.4", "11.4"],
}

lines = (ROOT / "REQUIREMENTS.md").read_text(encoding="utf-8").splitlines(keepends=True)
blocks: dict[str, list[str]] = {}
order: list[str] = []
front: list[str] = []
current: list[str] | None = None
for line in lines:
    match = re.match(r"^(#{1,3}) (.*)$", line)
    if match:
        keymatch = re.match(r"^(\d+[a-z]?(?:\.\d+)*)\.?\s", match.group(2))
        if keymatch:
            key = keymatch.group(1)
            assert key not in blocks, f"duplicate section {key}"
            blocks[key] = [line]
            order.append(key)
            current = blocks[key]
        else:
            # unnumbered heading: the doc title (goes to front) or a Part header (dropped)
            current = None
            if not blocks:
                front.append(line)
        continue
    if current is not None:
        current.append(line)
    elif not blocks:
        front.append(line)

mapped = {k for keys in MAPPING.values() for k in keys}
assert mapped == set(order), f"mapping/source drift: only-mapped={mapped - set(order)} only-source={set(order) - mapped}"

OUT = ROOT / "docs" / "requirements"
PROV = "<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->\n\n"
for rel, keys in MAPPING.items():
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join("".join(blocks[k]).rstrip() + "\n\n" for k in keys)
    path.write_text(PROV + body.rstrip() + "\n", encoding="utf-8")


def title_of(key: str) -> str:
    return re.sub(r"^#{1,3} \d+[a-z]?(?:\.\d+)*\.?\s*", "", blocks[key][0]).strip()


rows = []
for key in order:
    rel = next(rel for rel, keys in MAPPING.items() if key in keys)
    rows.append(f"| §{key} | {title_of(key)} | {rel} |")
preamble = "".join(front[1:]).strip()  # original intro, minus the old H1
index_md = (
    "# Aviato requirements — § index\n\n"
    + preamble
    + "\n\n> Split from the monolithic REQUIREMENTS.md on 2026-07-11. § numbering is preserved\n"
    + "> verbatim in the split files, so code citations like §5.2 remain valid. Start with\n"
    + "> `core/` for principles and contracts; each `modules/<module>/` holds one capability's\n"
    + "> flows plus its `backlog.md`.\n\n"
    + "## § → file index\n\n| § | Section | File |\n|---|---|---|\n"
    + "\n".join(rows)
    + "\n"
)
(OUT / "README.md").write_text(index_md, encoding="utf-8")

# ---------------- ARCHITECTURE.md ----------------
arch_lines = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8").splitlines(keepends=True)
sections: dict[str, list[str]] = {"front": []}
cursor = "front"
for line in arch_lines:
    match = re.match(r"^## (.+?)\s*$", line)
    if match:
        cursor = match.group(1)
        sections[cursor] = []
    sections[cursor].append(line)

AMAP = {
    "overview.md": ["front", "Purpose", "Boundaries", "Non-Goals For The Current Implementation"],
    "infrastructure.md": ["Current Components"],
    "data-flow.md": ["Policy Source", "Release Architecture", "Branch Protection Architecture"],
    "validation.md": ["Validation"],
}
amapped = {k for keys in AMAP.values() for k in keys}
assert amapped == set(sections), f"arch drift: {amapped ^ set(sections)}"
AOUT = ROOT / "docs" / "architecture"
AOUT.mkdir(parents=True, exist_ok=True)
APROV = "<!-- Split from ARCHITECTURE.md (2026-07-11). -->\n\n"
for rel, keys in AMAP.items():
    body = "".join("".join(sections[k]).rstrip() + "\n\n" for k in keys)
    (AOUT / rel).write_text(APROV + body.rstrip() + "\n", encoding="utf-8")

print(f"requirements: {len(MAPPING) + 1} files, {len(order)} sections; architecture: {len(AMAP)} files")
```

- [ ] **Step 2: Run it**

Run: `python3 <scratchpad>/split_docs.py`
Expected: `requirements: 33 files, 77 sections; architecture: 4 files` (section count = every `#`/`##`/`###` numbered heading; if the assert fires, a heading key is missing from MAPPING — fix MAPPING, not the source).

- [ ] **Step 3: Spot-check the output**

Run: `grep -rn '^```mermaid' docs/requirements | wc -l`
Expected: `23` (every Mermaid diagram preserved).
Run: `head -5 docs/requirements/modules/onboarding/flow.md`
Expected: provenance comment, then `### 5.2 Repository onboarding (provision-new and adopt-existing)`.

- [ ] **Step 4: Replace REQUIREMENTS.md with the pointer stub**

Full new content of `REQUIREMENTS.md`:

```markdown
# Aviato — Requirements & Architecture

The requirements were split into per-module documents on 2026-07-11. Original
§ numbering is preserved verbatim in the split files, so citations like "§5.2"
in code docstrings remain valid.

- **§ index / entry point:** [docs/requirements/README.md](docs/requirements/README.md)
- Core principles & contracts: `docs/requirements/core/`
- Per-module process flows & plug-ins: `docs/requirements/modules/`

`tests/test_docs_index.py` guards that every § cited in `aviato/**/*.py`
resolves through the index.
```

- [ ] **Step 5: Run the guard test — green — then the full suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_docs_index.py -q` → Expected: `2 passed`.
Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q` → Expected: all pass (was 725+ at last review). If `§9.2`-style entries fail, they belong in `LITERAL_ABSENT_OK` only after confirming the literal truly never existed in the monolith (`git show main:REQUIREMENTS.md | grep -c "9\.2"`).

- [ ] **Step 6: Lint the new test, then commit**

Run: `ruff check tests/test_docs_index.py && black --check --line-length 120 --target-version py312 tests/test_docs_index.py`

```bash
git add tests/test_docs_index.py docs/requirements REQUIREMENTS.md
git commit -m "docs(requirements): split REQUIREMENTS.md into per-module docs/ tree with guarded § index"
```

---

### Task 3: docs/architecture/** + ARCHITECTURE.md stub

**Files:**
- Create: `docs/architecture/{overview,infrastructure,data-flow,validation}.md` (already written by Task 2's script run)
- Modify: `ARCHITECTURE.md` (→ pointer stub)

- [ ] **Step 1: Verify the four architecture files**

Run: `grep -c '^#' docs/architecture/*.md` — each file non-empty; `overview.md` contains "Purpose", "Boundaries", and "Non-Goals" headings; `data-flow.md` contains "Policy Source", "Release Architecture", "Branch Protection".

- [ ] **Step 2: Replace ARCHITECTURE.md with the pointer stub**

Full new content of `ARCHITECTURE.md`:

```markdown
# Aviato Architecture

Split on 2026-07-11 into [docs/architecture/](docs/architecture/):

- `overview.md` — purpose, boundaries, non-goals
- `infrastructure.md` — components (workflows, templates, rulesets, core engine, scripts)
- `data-flow.md` — policy source → rendering → apply; release + branch-protection architecture
- `validation.md` — the validation gate
```

- [ ] **Step 3: Commit**

```bash
git add docs/architecture ARCHITECTURE.md
git commit -m "docs(architecture): split ARCHITECTURE.md into docs/architecture/"
```

---

### Task 4: Update inbound references (CLAUDE.md, README.md)

**Files:**
- Modify: `CLAUDE.md` (3 edits), `README.md` (1 edit)

- [ ] **Step 1: CLAUDE.md edits** (exact old → new)

1. `` `REQUIREMENTS.md` mandates a composition of plug-in modules around an **agnostic`` → `` The requirements (`docs/requirements/`, § index in its README) mandate a composition of plug-in modules around an **agnostic``
2. ``exercise them live. Process flows reference `REQUIREMENTS.md` section numbers in`` → ``exercise them live. Process flows reference requirements § numbers (index: `docs/requirements/README.md`) in``
3. ``Docs (`README.md`, `ARCHITECTURE.md`, `REQUIREMENTS.md`) describe policy but are not authoritative.`` → ``Docs (`README.md`, `docs/architecture/`, `docs/requirements/`) describe policy but are not authoritative.``

- [ ] **Step 2: README.md edit** (lines ~228–229)

Old:
```
See `ARCHITECTURE.md` for the current implementation map and
`REQUIREMENTS.md` for the broader requirements-backed system design.
```
New:
```
See `docs/architecture/` for the current implementation map and
`docs/requirements/` (§ index in `docs/requirements/README.md`) for the
requirements-backed system design.
```

- [ ] **Step 3: Sweep for stragglers**

Run: `grep -rn 'REQUIREMENTS\.md\|ARCHITECTURE\.md' --include='*.md' --include='*.py' --include='*.yml' . | grep -v -e '^\./docs/superpowers' -e '^\./REQUIREMENTS.md' -e '^\./ARCHITECTURE.md' -e node_modules -e '\.docusaurus' -e build -e FINDINGS -e OVERLAY`
Expected: only `aviato/plugins/actionpins.py:860` ("see REQUIREMENTS §11.3 scope note" — still resolves via the stub; leave it) and the new `docs/requirements` provenance comments.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: point CLAUDE.md/README.md at the split docs tree"
```

---

### Task 5: Backlog seeding + retire the findings docs

**Files:**
- Create: `backlog.md` in `docs/requirements/core/` and every module dir (`onboarding`, `scaffolding`, `drift`, `reconcile`, `versioning`, `fleet`, `offboarding`, `security`, `languages/{python,node,swift}`, `deployment/{pypi,ghcr,docs-site,apple}` + `deployment/` and `languages/` parent dirs only if they receive items — they do: `deployment/backlog.md`)
- Delete: `WORKFLOW-HARDENING-PLAN.md`, `docs/recent-fixes.md` (git rm), `FINDINGS.md` (untracked — plain rm)

**Backlog file format** (every file):

```markdown
# <Module> backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [high] … — FINDINGS #1 / C12-W2 · reusable-release-gate.yml:90 …

## Settled — do not reopen

- …
```

- [ ] **Step 1: Verify the likely-done items and drop them**

For each, run the check; if it confirms "fixed", the item is NOT seeded (record dropped ids in the commit message body):

| # | Check |
|---|---|
| 13 | `grep -n 'min-release-age\|11.10' aviato/library/scaffold/files/npmrc.txt .github/workflows/reusable-node-ci.yml` — engines floor npm ≥11.10 present → done |
| 20 | `grep -n 'algolia' aviato/library/scaffold/files/docusaurus.config.js.txt` — no unconditional `themes:` double-load, opt-in variable → done |
| 35 | `aviato repin --help | grep open-pr` → done |
| 36 | `aviato scan --help | grep audit` → done |
| 44 | `grep -n yamllint scripts/validate.sh` → done |
| 45 | `grep -n 'requires-python\|py312' pyproject.toml` + `grep -n 'python3 -m build' scripts/validate.sh` → done |
| 47 | `grep -n 'tag_pattern' aviato/library/policy.yml` — `(0|[1-9][0-9]*)` components → done |
| 48 | `ls aviato/library/scaffold/files/ | grep -i -e contributing -e codeowners` → done |
| 58 | `ls LICENSE && grep -n license pyproject.toml` → done |
| 64 | `grep -n 'provision OWNER/REPO' CLAUDE.md` — has `--pin` → done |
| 5, 7, 14, 18, 19, 37 | verify per the item's own file:line pointer before seeding |

All other items: confirm the pointer still matches the described state (one targeted grep each — e.g. #6: `grep -n 'persist-credentials' .github/workflows/reusable-docker-ghcr.yml`), then seed.

- [ ] **Step 2: Seed still-open items per this mapping**

FINDINGS # → target backlog (WORKFLOW-HARDENING-PLAN C12-W items merge into the same entries as FINDINGS 1–4; keep each item's Verify line):

| Target backlog | FINDINGS items |
|---|---|
| `core/backlog.md` | 10, 14, 17, 38, 41, 42, 44, 45, 46, 47, 52, 54, 58, 61, 62, 63, 64, 65, 66, 67, 68 |
| `modules/onboarding/backlog.md` | 23, 25, F-2 |
| `modules/scaffolding/backlog.md` | 11, 22, 28, 43, 48, 50 |
| `modules/drift/backlog.md` | 26, 30 |
| `modules/reconcile/backlog.md` | 51 |
| `modules/versioning/backlog.md` | 2 (C12-W1), 9, 21, 35, 57, F-1 |
| `modules/fleet/backlog.md` | 31, 32, 33, 36 |
| `modules/offboarding/backlog.md` | (none — create with empty Open) |
| `modules/security/backlog.md` | 6, 8, 18, 24, 53, 59, 60 |
| `modules/languages/python/backlog.md` | 12, 49 |
| `modules/languages/node/backlog.md` | 13, 19, 29 |
| `modules/languages/swift/backlog.md` | 27 |
| `modules/deployment/backlog.md` | 1 (C12-W2), 7, 16 |
| `modules/deployment/pypi/backlog.md` | 15, 55, F-3 |
| `modules/deployment/ghcr/backlog.md` | 3 (C12-W3), 56 |
| `modules/deployment/docs-site/backlog.md` | 20, 37, 39, 40 |
| `modules/deployment/apple/backlog.md` | 4 (C12-W6), 5, 34 |

Copy each seeded item's substance from FINDINGS.md (summary, severity, file:line pointers, source ids, any ⚖ operator-decision marker and the recorded decision from the "Decisions resolved" section). For items 1–4 also carry the C12-W plan steps + Verify lines from WORKFLOW-HARDENING-PLAN.md, including its header caveat that they are operator-verified by design and need a release-capable pass.

- [ ] **Step 3: Distribute the anti-fickleness ledger into "Settled — do not reopen"**

| Target backlog | Settled entries (from FINDINGS.md guardrails + resolved decisions) |
|---|---|
| `core/backlog.md` | agnostic core: capabilities land as data/plugins, never core edits naming targets |
| `modules/security/backlog.md` | §11.3 detector semantics frozen (bashlex-AST taint, fail-closed, block-level verify; no interpreter enumeration/grep mirrors/second checker); zizmor scope decision (#18); npm/Node hardening only ever strengthened (S6) |
| `modules/versioning/backlog.md` | release gate keeps `merge-base --is-ancestor` — fixes may ADD SHA-binding, never tip equality; tag-only publishing, no stored release PAT, fail-closed `aviato-ref` |
| `modules/reconcile/backlog.md` | single-operator consent TOCTOU ACCEPTED (153fdfa) |
| `modules/scaffolding/backlog.md` | templates only regenerated via `scripts/regen-templates.py` |
| `modules/deployment/pypi/backlog.md` | pip-audit stays `--strict`, no severity filter |
| `modules/deployment/ghcr/backlog.md` | GHCR stays single-job OIDC; only byte-identity scan→push in scope |
| `modules/deployment/docs-site/backlog.md` | Algolia stays, configurable (cdbaaeb); docs for ALL releases kept, `docs-retention` optional cap default unlimited (#37) |

- [ ] **Step 4: Retire the source docs**

```bash
git rm WORKFLOW-HARDENING-PLAN.md docs/recent-fixes.md
cp FINDINGS.md "$TMPDIR/FINDINGS.retired.md"   # untracked — no git history; keep a safety copy
rm FINDINGS.md
```
(`docs/recent-fixes.md` is a done-log; its anti-flap role is carried by the Settled sections. Git history keeps the two tracked files; FINDINGS.md survives only via the seeded backlogs + the safety copy.)

- [ ] **Step 5: Run the suite, commit**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q` → all pass.

```bash
git add docs/requirements
git commit -m "docs(backlogs): seed per-module backlogs from FINDINGS/WORKFLOW-HARDENING-PLAN; retire source docs"
```
Commit body: list dropped (verified-done) item ids.

---

### Task 6: starter-kit module docs + the docs-structure skill

**Files:**
- Create: `docs/requirements/modules/starter-kit/conventions.md`, `docs/requirements/modules/starter-kit/backlog.md`
- Create: `starter/skills/docs-structure/SKILL.md`
- Modify: `starter/README.md` (add skill section)

- [ ] **Step 1: Write `docs/requirements/modules/starter-kit/conventions.md`**

```markdown
# Starter kit — normative conventions

The starter kit (`starter/`) is the vendored, no-engine distribution: each
consumer repo carries its own copies of the kit workflows; `starter/` holds the
masters. These decisions are normative for the kit and its consumers.

- **Releasing is a tag push.** `git tag X.Y.Z && git push origin X.Y.Z` is the
  ship decision — no release PRs, no version derivation. The workflow refuses a
  tag that doesn't match the version in source. Release triggers only on
  digit-initiated tags. Never create releases via the GitHub UI (tag collision
  with the workflow).
- Tag format `X.Y.Z` with optional `-alphaN`/`-betaN` (prereleases marked on the
  GitHub release). The GitHub release is created **last**, after publishing.
- Required check context is the job id `ci`; rulesets applied once via
  `starter/rulesets/apply-rulesets.sh` (idempotent).
- **Workflows are vendored, not referenced cross-repo.** PyPI trusted publishing
  matches the workflow file containing the publish step (`release.yml`) plus the
  `release` environment — structurally impossible through a shared cross-repo
  reusable workflow (FINDINGS F-3).
- Third-party actions digest-pinned; first-party ride major tags; pip tools in
  workflows exact-pinned. Dependabot bumps weekly.
- Container releases are multi-arch (amd64 + arm64 on native runners); each arch
  scanned before its bytes are pushed, then a manifest ties them together.
- Docs are Docusaurus everywhere (no mkdocs flavor); docs deploy on main pushes;
  native versioning (latest at root, main at `/dev`).
- Learnings from consumer repos are backported to the kit masters.
```

- [ ] **Step 2: Write `docs/requirements/modules/starter-kit/backlog.md`**

```markdown
# Starter kit backlog

## Open

- (none)

## Settled — do not reopen

- Docusaurus everywhere; no mkdocs flavor (OVERLAY G1, operator decision).
- Multi-arch container builds REQUIRED — amd64+arm64 native-runner matrix (G2).
- No infra/terraform profile (G3, operator decision).
```

- [ ] **Step 3: Write `starter/skills/docs-structure/SKILL.md`**

````markdown
---
name: docs-structure
description: Use when creating, organizing, or splitting project documentation — requirements, specs, architecture docs, findings, or backlogs. Establishes the canonical docs/ tree (per-module requirements with per-module backlog.md, architecture docs), Mermaid-only diagrams, and numbering-preservation rules for splitting monoliths that code cites.
---

# Project docs structure

Organize long-lived project documentation in this tree. It is language- and
framework-agnostic; adapt module names to the project's domains.

```
docs/
├─ requirements/
│  ├─ README.md              # entry point; section → file index when numbering exists
│  ├─ core/                  # cross-cutting principles, contracts, definitions of done
│  └─ modules/
│     └─ <module>/           # one directory per cohesive capability
│        ├─ <topic>.md       # small, single-purpose topic files
│        └─ backlog.md       # the ONLY backlog location for this module
├─ architecture/
│  ├─ overview.md            # purpose, boundaries, non-goals
│  ├─ infrastructure.md      # components and how they're wired
│  ├─ data-flow.md           # how data moves end to end
│  └─ data-schema.md         # persistent shapes (when the project has them)
└─ superpowers/              # dated design artifacts, if the project uses that workflow
   ├─ specs/YYYY-MM-DD-<topic>-design.md
   └─ plans/YYYY-MM-DD-<feature>.md
```

## Rules

1. **Module = cohesive capability.** Topics are small, single-purpose files.
   Families (languages, deployment targets, providers) become subdirectories
   under their module (e.g. `languages/python/`), each with its own topic
   files and `backlog.md`.
2. **Backlogs live per module.** Every module directory carries `backlog.md`
   with `## Open` and `## Settled — do not reopen` sections. Never create
   root-level findings/TODO monoliths; a new finding goes straight into the
   owning module's backlog. Entry format:
   `[severity] summary — source · file:line pointer`. Settled entries record
   deliberate decisions so future reviews don't reopen them.
3. **Diagrams are Mermaid, in the markdown.** Every diagram is a ```mermaid
   fenced block — never a committed image or binary, never ASCII art. Code and
   config examples remain ordinary fenced code blocks.
4. **Splitting a monolith that code cites:** preserve section numbering
   verbatim; never split one numbered subsection across files; maintain a
   number → file index in `docs/requirements/README.md`; leave the original
   path as a short pointer stub; add a test that every number cited in code
   resolves through the index.
5. **Specs and plans are dated artifacts**, separate from living requirements.
   Requirements are updated in place; specs/plans are not rewritten to match
   later reality.
````

- [ ] **Step 4: Add the skill to `starter/README.md`** — after the "Docs-site scaffold" section:

```markdown
### Agent skill (any repo)

`skills/docs-structure/` → copy to `.claude/skills/docs-structure/` (Claude
Code) and reference it from `AGENTS.md` for other agentic coders. It defines
the `docs/` tree convention: per-module requirements with per-module
`backlog.md`, architecture docs, and Mermaid-only diagrams in markdown.
```

- [ ] **Step 5: Commit**

```bash
git add docs/requirements/modules/starter-kit starter/skills starter/README.md
git commit -m "feat(starter): reusable docs-structure skill + starter-kit conventions module"
```

Note: installing the skill into this repo's own `.claude/skills/` is a manual
operator step (policy-protected path): `cp -r starter/skills/docs-structure ~/GitHub/aviato/.claude/skills/`.

---

### Task 7: Full gate + final verification

- [ ] **Step 1: Full strict gate, output to a log**

Run: `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh > "$TMPDIR/validate.log" 2>&1; echo "exit=$?"; tail -20 "$TMPDIR/validate.log"`
Expected: exit=0, no skip banner. If yamllint/ruff complain about new files, fix and re-run.

- [ ] **Step 2: Confirm §-integrity end to end**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_docs_index.py -q` → `2 passed`.
Run: `git show main:REQUIREMENTS.md | wc -l` vs `cat docs/requirements/*/*.md docs/requirements/modules/*/*.md docs/requirements/modules/*/*/*.md | wc -l` — split total within ~120 lines of 2,129 (provenance headers + dropped Part headers + backlog files account for the delta; a large shortfall means lost content).

- [ ] **Step 3: Commit any gate fixes, report**

Report: exact test count, gate result, files created/deleted, dropped backlog items. Do NOT push — the operator reviews and pushes.
```
