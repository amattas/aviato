# Docusaurus → Zensical Docs Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Docusaurus with Zensical (pip-based SSG + mike-fork versioning onto a docs branch) across the engine docs plug-in, the starter kit, and this repo's `website/`.

**Architecture:** The docs pipeline keeps its name (`docs-pages`), filename (`reusable-docs-pages.yml`), and hardening invariants (C12-W2 gated-sha, C12-W4 privilege split, §8.14 monotonic guard), but swaps npm/Docusaurus for pip/Zensical and artifact-Pages deploys for commits to a docs branch (`gh-pages` by default) handed from the read-only build job to a no-consumer-code push job via `git bundle`. Pages serving is decoupled and optional.

**Tech Stack:** zensical==0.0.50 · mike fork @ git+https://github.com/squidfunk/mike.git@2d4ad799442f4592db8ad53b179bfb33db8c69ac · pydoc-markdown==4.8.2 · Python 3.12.

**Spec:** `docs/superpowers/specs/2026-07-11-zensical-docs-design.md`

## Global Constraints

- Branch: `feat/zensical-docs`. Commit per task; **do not push**. Every commit message ends with:
  `Claude-Session: https://claude.ai/code/session_015oBvsuGofC7reacf66rWjV`
- Python env (mamba run is sandbox-blocked): `/opt/homebrew/Caskroom/miniforge/base/envs/aviato/bin/{python3,ruff,black}`; run suites/gates with `PATH=/opt/homebrew/Caskroom/miniforge/base/envs/aviato/bin:$PATH` so zizmor resolves. Pytest: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 … -q`. Redirect verbose output to the scratchpad and read only failures + summary.
- Exact pins everywhere: `zensical==0.0.50`, `mike @ git+https://github.com/squidfunk/mike.git@2d4ad799442f4592db8ad53b179bfb33db8c69ac`, `pydoc-markdown==4.8.2`.
- Invariants that must survive: `reusable-docs-pages.yml` keeps its filename (REQUIRED_FILES, RELEASE_WORKFLOWS, monotonic-parity list in `validation.py:38/58/544`), its tag-validation step (verbatim), the C12-W2 verify step (verbatim), the §8.14 `highest.py` heredoc (verbatim — `_check_monotonic_alias_parity` fails otherwise), and per-alias concurrency. Consumer-supplied `eval` steps never run in a job holding a write token (C12-W4).
- Templates under `templates/` are regenerated (`python3 scripts/regen-templates.py`), never hand-edited. The five `wf-docs-*.yml` resolve blocks must stay byte-identical (validation `finding 43` check).
- `docs/requirements/**` § headings are guarded by `tests/test_docs_index.py` — do not renumber or delete § headings; §13.3 is rewritten *in place* under its existing heading.

---

### Task 1: §11.3 gate — VCS pins must carry a full commit SHA

**Files:**
- Modify: `aviato/plugins/actionpins.py` (near `_unpinned_pip_packages`, ~line 669)
- Test: `tests/core/test_actionpins.py`

**Interfaces:**
- Produces: `_unpinned_pip_packages(rest: str) -> list[str]` additionally flags VCS/direct-reference tokens whose ref is not a 40-hex SHA. Signature unchanged; later tasks rely on `mike @ git+…@<40-hex>` passing and `git+…@master` / bare `git+…` failing, in both `pip install` args and requirements-file lines (`unpinned_requirements_lines` reuses it).

- [ ] **Step 1: Write the failing tests** (append to `tests/core/test_actionpins.py`, matching its existing style):

```python
import pytest

_MIKE_SHA = "2d4ad799442f4592db8ad53b179bfb33db8c69ac"


@pytest.mark.parametrize(
    ("token", "flagged"),
    [
        (f"git+https://github.com/squidfunk/mike.git@{_MIKE_SHA}", False),
        (f"mike @ git+https://github.com/squidfunk/mike.git@{_MIKE_SHA}", False),
        ("git+https://github.com/squidfunk/mike.git", True),
        ("git+https://github.com/squidfunk/mike.git@master", True),
        ("git+https://github.com/squidfunk/mike.git@2d4ad79", True),
        (f"mike @ git+https://github.com/squidfunk/mike.git@{_MIKE_SHA[:12]}", True),
    ],
)
def test_vcs_pip_installs_require_full_commit_sha(token: str, flagged: bool) -> None:
    from aviato.plugins.actionpins import _unpinned_pip_packages

    result = _unpinned_pip_packages(f" {token}")
    assert bool(result) is flagged, result
```

- [ ] **Step 2: Run to verify the 4 `flagged=True` cases fail** (VCS tokens are currently exempt):

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/core/test_actionpins.py -q -k vcs`
Expected: 4 failed, 2 passed.

- [ ] **Step 3: Implement.** In `_unpinned_pip_packages`, the current code skips VCS tokens (`git+…`) and `name @ url` direct references. Change both paths: instead of skipping, validate the ref. Add at module level near the other regexes:

```python
# §11.3 (Zensical/mike): a VCS requirement exposes no index version, so its ref MUST be an
# immutable full commit SHA — `git+…@<40-hex>`. A branch, tag, short SHA, or missing ref is
# a floating install and is flagged like any unpinned package.
_VCS_URL_RE = re.compile(r"\bgit\+[A-Za-z0-9+.-]+://\S+")
_VCS_FULL_SHA_RE = re.compile(r"@[0-9a-f]{40}$")
```

and where VCS/direct-reference tokens were excluded, flag them unless `_VCS_FULL_SHA_RE.search(url)` matches (strip any `#egg=…` fragment before the check: `url = url.split("#", 1)[0]`). Keep local paths, wheels, `-r` files, and `${…}` tokens exempt exactly as before.

- [ ] **Step 4: Run the full actionpins tests** — `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/core/test_actionpins.py tests/test_cli_lint_actions.py -q` → all pass (if an existing test asserted VCS tokens are never flagged, update that test to the new contract and say so in the commit body).

- [ ] **Step 5: Lint + commit**

```bash
ruff check aviato/plugins/actionpins.py tests/core/test_actionpins.py
git add aviato/plugins/actionpins.py tests/core/test_actionpins.py
git commit -m "feat(lint-actions): §11.3 gate requires full-SHA pins on VCS pip installs"
```

---

### Task 2: Denylist gains `zensical`

**Files:**
- Modify: `aviato/plugins/denylist.txt` (add line `zensical` next to `docusaurus`, keep `docusaurus`)
- Test: `tests/core/test_selfcheck.py`

- [ ] **Step 1: Failing test** (append; mirror the file's existing denylist-violation test shape — it writes a temp core file containing a denylisted word and asserts selfcheck flags it):

```python
def test_core_may_not_name_zensical(tmp_path):
    # Same harness as the existing docusaurus denylist test in this file: copy its
    # arrange/act lines exactly, substituting the word "zensical".
    ...
```

Concretely: locate the existing test that asserts `docusaurus` in a core file fails selfcheck, duplicate it as `test_core_may_not_name_zensical` with the word `zensical`. If the existing test is parametrized over denylist words, add `"zensical"` to its parameter list instead of a new function.

- [ ] **Step 2: Run** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/core/test_selfcheck.py -q` → the new case fails (word not yet denylisted).
- [ ] **Step 3:** Add `zensical` on its own line to `aviato/plugins/denylist.txt`.
- [ ] **Step 4: Run** the same command → all pass.
- [ ] **Step 5: Commit** — `git add aviato/plugins/denylist.txt tests/core/test_selfcheck.py && git commit -m "feat(selfcheck): core agnosticism denylist covers zensical"`

---

### Task 3: Rewrite `reusable-docs-pages.yml` (Zensical + mike, branch deploy)

**Files:**
- Modify: `.github/workflows/reusable-docs-pages.yml` (full replacement below)
- Modify: `aviato/library/pipelines.yaml` — `docs-pages:` entry becomes:

```yaml
docs-pages:
  # Zensical/mike branch deploy: the push job needs contents:write; no Pages/OIDC scopes.
  privileges: ["contents: write"]
  runner: linux
```

**Interfaces:**
- Produces: workflow_call inputs consumed by Task 5's callers: `working-directory` (default "."), `release-tag`, `gated-sha` (required), `docs-emit-command`, `docs-source-directory` (default "."), `docs-requirements` (default `requirements.txt`, relative to working-directory), `docs-branch` (default `gh-pages`), `docs-retention` (default 0), `aviato-ref` (deprecated no-op, kept for caller compat).
- Removed inputs (callers must not pass them): `node-version`, `install-command`, `lint-command`, `build-command`, `artifact-path`, `environment-name`.

- [ ] **Step 1: Replace the file.** Keep these blocks **verbatim from the current file**: the `Validate release tag` step (lines 113–135), the `Verify tag still points at the gated commit (C12-W2)` step (137–148), the `Monotonic guard` step (244–272 — heredoc byte-identical), the `concurrency` block (86–88), and the checkout step (104–111). New overall structure:

```yaml
name: Reusable Zensical Docs Publish

on:
  workflow_call:
    inputs:
      aviato-ref:
        description: Deprecated. Release validation is embedded in this pinned workflow.
        required: false
        type: string
        default: ""
      working-directory:
        required: false
        type: string
        default: "."
      release-tag:
        description: >-
          Tag to build/publish when invoked IN-RUN (branch context) by the release
          job. When empty the workflow runs in the classic tag-ref context.
        required: false
        type: string
        default: ""
      docs-emit-command:
        description: >-
          §12 language docs emission: a command that writes API/narrative markdown
          into the docs source tree (e.g. pydoc-markdown for Python) before the
          mike version deploy. Empty = narrative-only (Swift).
        required: false
        type: string
        default: ""
      docs-source-directory:
        required: false
        type: string
        default: "."
      docs-requirements:
        description: >-
          Exact-pinned pip requirements for the docs toolchain (zensical + the mike
          fork), relative to working-directory. Missing file fails closed (§11.3).
        required: false
        type: string
        default: "requirements.txt"
      docs-branch:
        description: >-
          Branch the versioned site is committed to. Pages serving from this branch
          is a separate, optional operator toggle — this workflow only pushes the
          branch and succeeds identically whether Pages is enabled or not.
        required: false
        type: string
        default: "gh-pages"
      gated-sha:
        description: >-
          The commit SHA the release gate validated (reusable-release-gate.yml's
          gated-sha output). C12-W2: build docs from this immutable commit — never
          the mutable tag — and re-verify the tag still points at it.
        required: true
        type: string
      docs-retention:
        description: >-
          Optional retention cap (§13.3). 0 — the default — keeps EVERY released
          version's docs; set N>0 to prune to the newest N versions on each release.
        required: false
        type: number
        default: 0

# C12-W4 (adapted for branch deploys): permissions are PER-JOB. The build job runs the
# consumer's emit `eval` and holds ONLY `contents: read`; mike commits land on a LOCAL
# branch handed off as a git bundle artifact. Only the separate push job — which runs
# no consumer code — holds `contents: write`.
permissions: {}

concurrency:
  group: pages-latest-${{ github.repository }}
  cancel-in-progress: false

jobs:
  build:
    name: Build versioned docs
    runs-on: ubuntu-latest
    permissions:
      contents: read
    outputs:
      highest: ${{ steps.guard.outputs.highest }}
    defaults:
      run:
        working-directory: ${{ inputs.working-directory }}
    steps:
      # [checkout step VERBATIM from current file]
      # [Validate release tag step VERBATIM]
      # [C12-W2 verify step VERBATIM]

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install docs toolchain (exact pins, §11.3)
        shell: bash
        env:
          DOCS_REQUIREMENTS: ${{ inputs.docs-requirements }}
        run: |
          set -euo pipefail
          if [ ! -f "${DOCS_REQUIREMENTS}" ]; then
            echo "::error::docs requirements file ${DOCS_REQUIREMENTS} is missing; refusing an unpinned toolchain install (§11.3)."
            exit 1
          fi
          python3 -m pip install --quiet -r "${DOCS_REQUIREMENTS}"

      # §12: emit language API docs BEFORE the mike deploy so the generated reference
      # is captured in this version's snapshot. Runs with a read-only token (C12-W4).
      - name: Emit language API docs
        if: ${{ inputs.docs-emit-command != '' }}
        shell: bash
        working-directory: ${{ inputs.docs-source-directory }}
        env:
          DOCS_EMIT_COMMAND: ${{ inputs.docs-emit-command }}
        run: eval "$DOCS_EMIT_COMMAND"

      # [Monotonic guard step VERBATIM — including the /tmp/highest.py heredoc]

      - name: Deploy version onto the local docs branch (mike)
        shell: bash
        env:
          RELEASE_TAG: ${{ steps.release.outputs.tag }}
          DOCS_BRANCH: ${{ inputs.docs-branch }}
          HIGHEST: ${{ steps.guard.outputs.highest }}
          RETENTION: ${{ inputs.docs-retention }}
        run: |
          set -euo pipefail
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          # Continue the existing published history when the branch exists (first deploy: absent is fine).
          git fetch origin "+refs/heads/${DOCS_BRANCH}:refs/heads/${DOCS_BRANCH}" || true
          # §8.14: EVERY policy-conformant release deploys its own version directory, but the
          # `latest` alias (and default) moves ONLY when this tag is the highest release.
          if [ "${HIGHEST}" = "true" ]; then
            mike deploy --branch "${DOCS_BRANCH}" --update-aliases "${RELEASE_TAG}" latest
            mike set-default --branch "${DOCS_BRANCH}" latest
          else
            echo "::warning::${RELEASE_TAG} is not the highest release; deploying its docs without moving latest (§8.14)."
            mike deploy --branch "${DOCS_BRANCH}" "${RELEASE_TAG}"
          fi
          if [ "${RETENTION}" -gt 0 ]; then
            python3 - "${RETENTION}" "${DOCS_BRANCH}" <<'PY'
          import re, subprocess, sys
          cap, branch = int(sys.argv[1]), sys.argv[2]
          rel = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta)(\d+))?$")
          rank = {None: 2, "beta": 1, "alpha": 0}
          def key(t):
              m = rel.match(t)
              return (int(m[1]), int(m[2]), int(m[3]), rank[m[4]], int(m[5] or 0)) if m else None
          out = subprocess.run(["mike", "list", "--branch", branch], check=True, capture_output=True, text=True).stdout
          versions = [line.split()[0] for line in out.splitlines() if line.strip()]
          keyed = sorted((v for v in versions if key(v)), key=key, reverse=True)
          for v in keyed[cap:]:
              subprocess.run(["mike", "delete", "--branch", branch, v], check=True)
              print(f"pruned {v}")
          PY
          fi

      - name: Bundle the docs branch for the push job
        shell: bash
        env:
          DOCS_BRANCH: ${{ inputs.docs-branch }}
        run: git bundle create /tmp/docs.bundle "refs/heads/${DOCS_BRANCH}"

      - name: Hand off docs branch bundle
        uses: actions/upload-artifact@v7
        with:
          name: aviato-docs-branch
          path: /tmp/docs.bundle
          retention-days: 1
          if-no-files-found: error

  # C12-W4: the ONLY job with contents:write. Runs no consumer code — it verifies the
  # bundle and fast-forward-pushes the docs branch. Enabling Pages to SERVE this branch
  # is a separate operator toggle; this job neither reads nor mutates Pages settings.
  push:
    name: Push docs branch
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          persist-credentials: true
          fetch-depth: 1

      - name: Fetch docs branch bundle
        uses: actions/download-artifact@v4
        with:
          name: aviato-docs-branch
          path: /tmp

      - name: Verify and fast-forward push
        shell: bash
        env:
          DOCS_BRANCH: ${{ inputs.docs-branch }}
        run: |
          set -euo pipefail
          git bundle verify /tmp/docs.bundle
          git fetch /tmp/docs.bundle "refs/heads/${DOCS_BRANCH}:refs/remotes/bundle/${DOCS_BRANCH}"
          if git fetch origin "+refs/heads/${DOCS_BRANCH}:refs/remotes/origin/${DOCS_BRANCH}" 2>/dev/null; then
            # Never rewrite published history: the bundle must extend what is on origin.
            if ! git merge-base --is-ancestor "refs/remotes/origin/${DOCS_BRANCH}" "refs/remotes/bundle/${DOCS_BRANCH}"; then
              echo "::error::bundle does not fast-forward origin/${DOCS_BRANCH}; refusing to push (concurrent deploy or rewritten history)."
              exit 1
            fi
          fi
          git push origin "refs/remotes/bundle/${DOCS_BRANCH}:refs/heads/${DOCS_BRANCH}"
```

Where a comment says `[… VERBATIM …]`, copy that step from the pre-edit file exactly (use `git show HEAD:.github/workflows/reusable-docs-pages.yml`). The C12-W5 artifact-restore step, npm-hardening step, Configure Pages, Install/Lint/Build/version-cut/Persist/Upload-Pages steps, and the whole `deploy` job are **deleted** — versions persist on the docs branch itself now.

- [ ] **Step 2: Update `aviato/library/pipelines.yaml`** `docs-pages` entry as shown in Files above.
- [ ] **Step 3: Static checks:** `PATH=/opt/homebrew/bin:$PATH actionlint .github/workflows/reusable-docs-pages.yml` → clean. Then `PATH=<envbin>:$PATH python3 -m pytest tests/test_validation.py tests/test_workflow_guards.py -q` — expect failures ONLY from checks that inspect callers/templates not yet updated (Tasks 4–5); anything complaining about the monotonic heredoc or RELEASE_WORKFLOWS invariants in THIS file means a verbatim block was mangled — fix before proceeding. Record the failing-test list in the commit body as known-transitional.
- [ ] **Step 4: Commit** — `git add .github/workflows/reusable-docs-pages.yml aviato/library/pipelines.yaml && git commit -m "feat(docs): reusable docs workflow — Zensical + mike branch deploy, C12-W4 bundle handoff"`

---

### Task 4: Scaffold data swap (templates, metadata, bundles, profiles, validation, composition tests)

**Files:**
- Create: `aviato/library/scaffold/files/zensical.toml.txt`, `aviato/library/scaffold/files/docs-requirements.txt.txt`
- Keep (rename content only): `aviato/library/scaffold/files/docs-intro.md.txt` (content unchanged — Zensical consumes plain markdown)
- Delete: `aviato/library/scaffold/files/{docusaurus.config.js.txt,docusaurus.config.algolia.js.txt,docs-package.json.txt,docs-sidebars.js.txt,docs-eslint.config.mjs.txt}`
- Create metadata: `aviato/library/scaffold/zensical-config.yaml`, `aviato/library/scaffold/docs-requirements.yaml`
- Delete metadata: `aviato/library/scaffold/{docusaurus-config.yaml,docusaurus-config-algolia.yaml,docs-package.yaml,docs-sidebars.yaml,docs-eslint-config.yaml,docs-npmrc.yaml}` (repo-root `npmrc.txt` used by Node CI profiles stays)
- Modify: the 6 bundle files `aviato/library/bundles/scaffold/{python-library,python-service,python-component,node-service,swift-app,aviato-library}-sc.yaml` — docs entries become exactly: the profile's `wf-docs-*` + `zensical-config` + `docs-intro` + `docs-requirements`
- Modify: the 6 profile YAMLs — delete the `algolia`, `algolia-app-id`, `algolia-search-api-key`, `algolia-index-name` variable declarations
- Modify: `aviato/validation.py` REQUIRED_FILES — swap deleted scaffold paths for the two new ones
- Test: `tests/core/test_composition.py`, `tests/core/test_dayzero_profiles.py`

- [ ] **Step 1: Failing test.** In `tests/core/test_composition.py`, next to `test_docs_opt_in_adds_docs_pipeline` (line ~275), add:

```python
def test_docs_opt_in_seeds_zensical_scaffold(resolved_python_library_docs):
    # Use the same fixture/arrange pattern as test_docs_opt_in_adds_docs_pipeline —
    # resolve python-library with docs=true, then inspect the scaffold file set.
    names = {s.name for s in resolved_python_library_docs.scaffold}
    assert {"zensical-config", "docs-intro", "docs-requirements"} <= names
    assert not any("docusaurus" in n or "algolia" in n or n in {"docs-package", "docs-sidebars", "docs-eslint-config", "docs-npmrc"} for n in names)
```

Adapt the arrange lines to the file's actual fixture (read the neighboring test first); the two assertions are the contract.

- [ ] **Step 2: Run** → fails (docusaurus scaffold names still present).
- [ ] **Step 3: Write the new templates.**

`zensical.toml.txt` — reuse the **same `{{ }}` variable names** the deleted `docusaurus.config.js.txt` used for site title/owner/repo (read it via `git show HEAD:…` before deleting; do not invent new variable names — `aviato/core/variables.py` validates declared vs used):

```toml
[project]
site_name = "{{ project-name }}"
site_url = "https://{{ owner }}.github.io/{{ repo }}/"
repo_url = "https://github.com/{{ owner }}/{{ repo }}"
docs_dir = "docs"

[project.extra.version]
provider = "mike"
default = "latest"
alias = true
```

(substituting the actual variable spellings found in the Docusaurus template.)

`docs-requirements.txt.txt`:

```text
# Aviato-managed docs toolchain (§13.3). Exact pins only (§11.3); Dependabot bumps zensical.
zensical==0.0.50
mike @ git+https://github.com/squidfunk/mike.git@2d4ad799442f4592db8ad53b179bfb33db8c69ac
```

Metadata `zensical-config.yaml` (mirror the shape of the deleted `docusaurus-config.yaml`, dropping the algolia `when` clause): `output_path: website/zensical.toml`, `when: docs=true`, seed-once. `docs-requirements.yaml`: `output_path: website/requirements.txt`, `when: docs=true`, **managed** (auto-updated, like the deleted docs-npmrc.yaml). `docs-intro.yaml` already exists — change only its `output_path` if it referenced a Docusaurus-specific location (it targets `website/docs/intro.md`; keep).

- [ ] **Step 4: Apply the deletions/edits** listed under Files (bundles, profiles, REQUIRED_FILES). Search for leftover references: `grep -rn 'docusaurus\|algolia' aviato/library aviato/*.py --include='*.yaml' --include='*.yml' --include='*.py' -il` → expect only `denylist.txt` (docusaurus stays denylisted) and `zizmor.yml` if it names workflow paths (update it if so).
- [ ] **Step 5: Run** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/core -q` → all pass (fix `test_dayzero_profiles.py` expectations that enumerate the old scaffold names or algolia variables — update them to the new file set; that is the intended contract change).
- [ ] **Step 6: Commit** — `git add -A aviato/library aviato/validation.py tests/core && git commit -m "feat(scaffold): docs scaffold is Zensical — 3 templates, no algolia variables"`

---

### Task 5: wf-docs callers ×5, `aviato-docs.yml`, regenerated templates

**Files:**
- Modify: `aviato/library/scaffold/files/wf-docs-{python-library,python-service,python-component,node-service,swift-app}.yml`
- Modify: `.github/workflows/aviato-docs.yml`
- Regenerate: `templates/` via `python3 scripts/regen-templates.py`

**Interfaces:**
- Consumes: Task 3's input surface (`docs-requirements`, `docs-branch` defaults are fine — callers pass `working-directory: website`, so requirements resolve to `website/requirements.txt`).

- [ ] **Step 1: Edit each wf-docs body identically** (resolve/release-gate/security jobs stay byte-identical across the five files — validation enforces):
  1. Header comment: `# Multi-version Docusaurus docs publish (§13.3)…` → `# Multi-version Zensical docs publish (§13.3), versioned onto a docs branch by mike…`.
  2. In the `docs:` job: `permissions:` becomes `actions: read` + `contents: write` (drop `id-token: write`, `pages: write`).
  3. In `with:`: keep `working-directory: website`, `release-tag`, `gated-sha`, `docs-source-directory`, and the file's existing `docs-emit-command` **unchanged** (they emit plain markdown already); remove any `node-version`/`install-command`/`lint-command`/`build-command`/`artifact-path`/`environment-name` keys if present.
- [ ] **Step 2: Apply the same three edits to `.github/workflows/aviato-docs.yml`** (its docs job at lines 98–117; emit command stays pydoc-markdown==4.8.2).
- [ ] **Step 3: Regenerate templates:** `python3 scripts/regen-templates.py` → `templates/` diffs match the caller edits only.
- [ ] **Step 4: Validate:** `PATH=<envbin>:$PATH ./scripts/validate.sh > <scratchpad>/validate-task5.log 2>&1; tail -5 <scratchpad>/validate-task5.log` — the finding-43 parity checks (pydoc pin, resolve-block identity, template parity) and `_check_monotonic_alias_parity` must pass. `aviato lint-actions` must pass with the mike git+SHA pin (Task 1's rule proves out here).
- [ ] **Step 5: Commit** — `git add aviato/library/scaffold/files/wf-docs-*.yml .github/workflows/aviato-docs.yml templates && git commit -m "feat(docs): wf-docs callers call the Zensical branch-deploy workflow"`

---

### Task 6: Starter kit docs-site swap + README

**Files:**
- Delete: `starter/docs-site/{package.json,package-lock.json,docusaurus.config.js,sidebars.js,npmrc,src/,build/,static/,.docusaurus/}` (everything except `docs/`)
- Create: `starter/docs-site/zensical.toml`, `starter/docs-site/requirements.txt`, rewrite `starter/docs-site/docs.yml`; keep `starter/docs-site/docs/index.md`
- Modify: `starter/README.md` (docs rows + docs-site section + one-time setup + migration recipe)

- [ ] **Step 1: `starter/docs-site/zensical.toml`** (kit uses ALL-CAPS placeholders):

```toml
[project]
site_name = "PROJECT"
site_url = "https://OWNER.github.io/REPO/"
repo_url = "https://github.com/OWNER/REPO"
docs_dir = "docs"

[project.extra.version]
provider = "mike"
default = "latest"
alias = true
```

`starter/docs-site/requirements.txt`: same two pinned lines as Task 4's `docs-requirements.txt.txt` (without the Aviato-managed comment; comment: `# Docs toolchain — exact pins; Dependabot (pip, /website) bumps zensical.`).

- [ ] **Step 2: Rewrite `starter/docs-site/docs.yml`:**

```yaml
# Docs — Zensical + mike, versioned onto the gh-pages branch.
# main push  -> `mike deploy dev`             (rolling dev docs)
# tag push   -> `mike deploy X.Y.Z latest`    (latest moves only for the highest release)
# Copy to: .github/workflows/docs.yml ; site source lives in website/.
# One-time (OPTIONAL — only if you want the branch SERVED): repo Settings → Pages →
# Source: Deploy from a branch → gh-pages. The workflow only pushes the branch and
# works identically with Pages on or off.
#
# CUSTOMIZE:
#  - DOCS_DIR if the Zensical site doesn't live in website/
#  - the PYTHON API DOCS block for Python repos (pydoc-markdown)
name: Docs

on:
  push:
    branches: [main]
    tags: ["[0-9]*"]
  workflow_dispatch:

permissions:
  contents: write

env:
  DOCS_DIR: website

concurrency:
  group: docs
  cancel-in-progress: false

jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
          fetch-tags: true
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - name: Install docs toolchain (exact pins)
        run: python -m pip install --quiet -r "${DOCS_DIR}/requirements.txt"
      # PYTHON API DOCS (optional): generate an API reference from docstrings.
      # - name: Generate API reference
      #   run: |
      #     python -m pip install --quiet -e . "pydoc-markdown==4.8.2"
      #     mkdir -p ${DOCS_DIR}/docs/api
      #     pydoc-markdown -I src -p PACKAGE > ${DOCS_DIR}/docs/api/reference.md
      - name: Deploy
        working-directory: ${{ env.DOCS_DIR }}
        run: |
          set -euo pipefail
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          if [ "${GITHUB_REF_TYPE}" = "tag" ]; then
            TAG="${GITHUB_REF_NAME}"
            if [[ ! "${TAG}" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(alpha|beta)[0-9]+)?$ ]]; then
              echo "not a release tag (${TAG}); skipping docs"; exit 0
            fi
            HIGHEST="$(git tag --list | python3 -c '
          import sys, re
          rel = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta)(\d+))?$")
          rank = {None: 2, "beta": 1, "alpha": 0}
          def key(t):
              m = rel.match(t.strip())
              return (int(m[1]), int(m[2]), int(m[3]), rank[m[4]], int(m[5] or 0)) if m else None
          cand = sys.argv[1]; ck = key(cand)
          keys = [k for k in map(key, sys.stdin) if k]
          print("true" if ck and max(keys + [ck]) == ck else "false")
          ' "${TAG}")"
            if [ "${HIGHEST}" = "true" ]; then
              mike deploy --push --update-aliases "${TAG}" latest
              mike set-default --push latest
            else
              echo "::warning::${TAG} is not the highest release; not moving latest."
              mike deploy --push "${TAG}"
            fi
          else
            mike deploy --push dev
          fi
```

(The kit is standalone — one job is acceptable here; the kit's threat model accepts consumer code = your own repo. The engine keeps the two-job split.)

- [ ] **Step 3: `starter/README.md`:** update the docs-site row in "What to copy where" (copy set: `docs-site/docs.yml` → `.github/workflows/docs.yml`; `zensical.toml`, `requirements.txt`, `docs/` → `website/`); rewrite the "Docs-site scaffold" section (Zensical: built-in search + Mermaid, versioning via mike onto gh-pages — latest alias at root, `dev` from main; pydoc-markdown block for Python repos; gitignore `website/site`); one-time setup step 3 becomes "**Pages (optional, docs sites only):** Settings → Pages → Source: Deploy from a branch → `gh-pages` — flip on/off anytime; the workflow pushes the branch either way"; update "Conventions baked in" bullet "Docs are Docusaurus everywhere" → "Docs are Zensical everywhere (2026-07-11 decision, supersedes Docusaurus-everywhere); repos on Docusaurus/mkdocs convert during migration"; append a `### Migrating a Docusaurus docs site` subsection: delete `website/{package.json,package-lock.json,docusaurus.config.js,sidebars.js,.npmrc,src}`, keep `website/docs/`, add `zensical.toml` + `requirements.txt` from the kit, swap `docs.yml`, delete `versioned_docs/ versioned_sidebars/ versions.json` (history now lives on gh-pages), flip Pages source if serving, then `mike deploy --push <current-release> latest && mike set-default --push latest && mike deploy --push dev`.
- [ ] **Step 4: Prove the scaffold builds:** `cd starter/docs-site && PATH=<envbin>:$PATH python3 -m pip install -r requirements.txt --quiet && python3 -m zensical build` (or the `zensical` console script) → build succeeds into `site/`; add a `\`\`\`mermaid` block to a scratch copy of `docs/index.md` and rebuild to confirm Mermaid renders (inspect the emitted HTML for a mermaid container). Delete `site/` afterwards.
- [ ] **Step 5: Commit** — `git add -A starter && git commit -m "feat(starter): docs-site scaffold is Zensical + mike (branch deploy, optional Pages)"`

---

### Task 7: Convert this repo's `website/`

**Files:**
- Delete: `website/{package.json,package-lock.json,docusaurus.config.js,sidebars.js,eslint.config.mjs,.npmrc,build/,.docusaurus/}`
- Create: `website/zensical.toml` (real values: site_name "Aviato", site_url `https://amattas.github.io/aviato/`, repo_url `https://github.com/amattas/aviato`, same `[project.extra.version]` block), `website/requirements.txt` (same two pins)
- Modify: `.gitignore` — replace `website/build` + `website/.docusaurus` entries with `website/site`; add `starter/docs-site/site`
- Modify: `.github/dependabot.yml` — add:

```yaml
  - package-ecosystem: pip
    directory: /website
    schedule:
      interval: weekly
```

- [ ] **Step 1:** Apply the file changes above (keep `website/docs/` content).
- [ ] **Step 2:** Build locally: `cd website && PATH=<envbin>:$PATH python3 -m pip install -r requirements.txt --quiet && zensical build` → succeeds; `ls site/index.html`. Remove `site/`.
- [ ] **Step 3: Commit** — `git add -A website .gitignore .github/dependabot.yml && git commit -m "feat(website): aviato self-docs on Zensical"`

---

### Task 8: Requirements §13.3 rewrite + decision records

**Files:**
- Modify: `docs/requirements/modules/deployment/docs-site/requirements.md` (rewrite the §13.3 body **under the existing `### 13.3` heading** — do not change the heading line)
- Modify: `docs/requirements/modules/deployment/docs-site/backlog.md`, `docs/requirements/modules/starter-kit/backlog.md`, `docs/requirements/modules/starter-kit/conventions.md`
- Modify: `docs/architecture/infrastructure.md`, `docs/architecture/data-flow.md` (docs-pipeline mentions)

- [ ] **Step 1: §13.3 rewrite.** Keep the heading `### 13.3 Documentation site (…)` (retitle the parenthetical to `Zensical → docs branch, multi-version` — the § number and heading level must not change; `tests/test_docs_index.py` guards resolution, and `13.3` must stay literally present). New body covers: opt-in via `docs: true`; toolchain = zensical + mike fork, exact pins in `website/requirements.txt` (§11.3: VCS pin = full SHA); stages: gated checkout → pinned install → emit language docs → §8.14 monotonic guard → mike version deploy on local branch (+ optional retention prune via `mike delete`) → bundle handoff → fast-forward push by the no-consumer-code job; deploy target is the `docs-branch` (default `gh-pages`); **Pages serving is decoupled and optional**; DoD: after a release deploy the docs branch contains the version directory with correct alias state (latest moved iff highest), and — when the operator has Pages enabled — latest resolves at the site root, built-in search returns results, Mermaid renders, sitemap present; auth = platform token `contents: write` on the push job only.
- [ ] **Step 2: Ledgers.** `deployment/docs-site/backlog.md`: under `## Settled — do not reopen` add "Zensical everywhere — supersedes 'Docusaurus everywhere' (G1) and 'Algolia stays, configurable' (operator decision 2026-07-11); search is Zensical built-in."; under `## Open` add "[low] Replace the mike bridge with Zensical-native versioning when it ships — mike fork pinned at 2d4ad79 meanwhile. — spec 2026-07-11". `starter-kit/backlog.md`: same Settled supersession line. `starter-kit/conventions.md`: update the Docusaurus bullet to Zensical (mike/gh-pages, optional Pages serving).
- [ ] **Step 3:** Update `docs/architecture/{infrastructure,data-flow}.md` docs-pipeline mentions (npm/Pages-artifact wording → pip/mike/docs-branch; the C12-W4 note now reads "bundle handoff; only the push job writes").
- [ ] **Step 4:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_docs_index.py -q` → 2 passed.
- [ ] **Step 5: Commit** — `git add docs && git commit -m "docs(requirements): §13.3 is Zensical/mike; decision records supersede Docusaurus + Algolia"`

---

### Task 9: Pin-parity check, full gate, sweep

**Files:**
- Modify: `aviato/validation.py` (inside the finding-43 parity function, after the pydoc-markdown pin check at ~line 314)
- Test: `tests/test_validation_negative.py`

- [ ] **Step 0a: Failing test** (append to `tests/test_validation_negative.py`, using its existing mutate-a-copy harness — mirror the arrange pattern of the neighboring negative tests):

```python
def test_docs_toolchain_pin_drift_is_flagged(tmp_repo_copy):
    # Change the zensical pin in ONE of the three docs requirements sources and
    # assert validate() reports the drift (finding 43 mechanism).
    target = tmp_repo_copy / "starter" / "docs-site" / "requirements.txt"
    target.write_text(target.read_text().replace("zensical==0.0.50", "zensical==0.0.49"))
    errors = run_validate(tmp_repo_copy)  # use this file's existing helper for invoking validate()
    assert any("docs toolchain pins differ" in e for e in errors), errors
```

- [ ] **Step 0b: Run** → fails (no such check). **Implement** in the finding-43 parity function:

```python
    docs_pin_sources = [
        root / "aviato" / "library" / "scaffold" / "files" / "docs-requirements.txt.txt",
        root / "website" / "requirements.txt",
        root / "starter" / "docs-site" / "requirements.txt",
    ]
    pin_sets = {
        str(p.relative_to(root)): sorted(
            line.split("#", 1)[0].strip()
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        )
        for p in docs_pin_sources
        if p.is_file()
    }
    if len(set(map(tuple, pin_sets.values()))) > 1:
        errors.append(f"docs toolchain pins differ across requirements sources: {pin_sets} (finding 43)")
```

Run the test again → passes. Commit with Step 3 below.

- [ ] **Step 1:** `grep -rn -i 'docusaurus\|algolia' --include='*.py' --include='*.yml' --include='*.yaml' --include='*.toml' --include='*.md' . | grep -v -e node_modules -e '\.git/' -e docs/superpowers -e denylist -e 'docs/requirements/modules/deployment/docs-site' -e 'backlog.md' -e OVERLAY` — remaining hits must be only: historical/dated docs, decision records, the denylist, and migration-recipe text in starter/README.md. Fix anything else.
- [ ] **Step 2:** `AVIATO_STRICT_TOOLS=1 PATH=<envbin>:$PATH ./scripts/validate.sh > <scratchpad>/validate-final.log 2>&1; echo exit=$?; tail -10 <scratchpad>/validate-final.log` → exit=0, no skip banner. Full suite: `PATH=<envbin>:$PATH python3 -m pytest -q` → all green; report exact counts.
- [ ] **Step 3:** Commit any fixes; report counts, files created/deleted, and the two local `zensical build` results. Do not push.
