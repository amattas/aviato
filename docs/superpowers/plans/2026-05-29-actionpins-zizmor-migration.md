> **STATUS: IMPLEMENTED** (zizmor==pinned + bundled config + fail-closed fetch check
> shipped; common-lint runs `aviato lint-actions`. The unchecked boxes below are the
> historical plan, not pending work).

# actionpins → zizmor + fail-closed fetch check — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 601-line hand-rolled supply-chain detector (and its in-CI grep mirror) with `zizmor` for `uses:`/image pinning plus a small fail-closed fetch-execute check, so every §11.3 check has one implementation and stops flapping.

**Architecture:** `aviato lint-actions` becomes the single entry point used by both consumer CI and `aviato validate`. It shells out to a pinned `zizmor` (a dependency of `aviato`, configured by a bundled `zizmor.yml`) for `unpinned-uses`/`unpinned-images`, runs a ~30-line fail-closed Python rule for `curl|bash` fetch-execute, keeps the existing pip exact-version check, and keeps a tiny placeholder-aware `uses:` check for scaffold templates that zizmor can't parse. The in-CI grep mirror is deleted.

**Tech Stack:** Python 3.11, PyYAML, `zizmor` (pinned), pytest, ruff. GitHub Actions reusable workflows.

**Spec:** `docs/superpowers/specs/2026-05-29-actionpins-zizmor-migration-design.md`

**Scope note — deliberate behavior change (record in docs):** the old detector flagged `docker run img:tag` *inside `run:` shell blocks*. That check is **dropped**; zizmor's `unpinned-images` covers structured `container:`/`services:` image keys, and ad-hoc `docker run` in a shell is no longer gated (it was niche and the source of R9-4). This is intentional and must be stated in REQUIREMENTS §11.3 (Task 8).

---

### Task 1: Pin zizmor as a dependency + bundle its config

**Files:**
- Modify: `pyproject.toml` (dependencies + package-data)
- Create: `aviato/library/zizmor.yml`
- Test: `tests/core/test_zizmor_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_zizmor_config.py
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def test_zizmor_is_pinned_exactly() -> None:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    # §11.3: tools are pinned to an EXACT version, never a floor/floating.
    assert 'zizmor==' in text, "zizmor must be an exact-version (==) dependency of aviato"


def test_bundled_zizmor_config_encodes_the_pin_policy() -> None:
    cfg = yaml.safe_load((REPO / "aviato" / "library" / "zizmor.yml").read_text(encoding="utf-8"))
    policies = cfg["rules"]["unpinned-uses"]["config"]["policies"]
    assert policies["actions/*"] == "ref-pin"
    assert policies["github/*"] == "ref-pin"
    assert policies["amattas/aviato/*"] == "ref-pin"   # the one sanctioned mutable Library self-ref
    assert policies["*"] == "hash-pin"                 # everything else SHA-required
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/core/test_zizmor_config.py -v`
Expected: FAIL (`zizmor==` not in pyproject; `aviato/library/zizmor.yml` missing → FileNotFoundError).

- [ ] **Step 3: Add the dependency + package-data glob**

In `pyproject.toml`, change the `dependencies` list to:

```toml
dependencies = [
  "PyYAML>=6.0",
  # §11.3: zizmor performs uses:/image pin enforcement; pinned EXACTLY (Dependabot bumps it).
  "zizmor==1.25.2",
]
```

The existing `[tool.setuptools.package-data]` glob `aviato = ["library/**/*", "plugins/*.txt"]` already ships `library/zizmor.yml` — no change needed there.

- [ ] **Step 4: Create the bundled config**

```yaml
# aviato/library/zizmor.yml
# §11.3 single source of truth for action/image pinning, shipped in the wheel and passed to
# zizmor via `--config` by `aviato lint-actions` (so every consumer gets the Library policy
# without authoring their own config). Most-specific pattern wins.
#
# Only `unpinned-uses` and `unpinned-images` are GATED by aviato today (see
# aviato/plugins/zizmor_scan.py:_GATED_AUDITS). zizmor still runs its other audits; their
# findings are intentionally ignored here until explicitly adopted.
rules:
  unpinned-uses:
    config:
      policies:
        actions/*: ref-pin          # first-party GitHub — branch/tag allowed
        github/*: ref-pin
        amattas/aviato/*: ref-pin    # the one sanctioned mutable Library self-ref (§6.1/§11.3)
        "*": hash-pin                # everything else: 40-hex SHA required
```

- [ ] **Step 5: Install the new dependency**

Run: `python3 -m pip install -e .[dev]`
Expected: installs `zizmor` (a binary wheel). Verify: `zizmor --version` prints a version.

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 -m pytest tests/core/test_zizmor_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml aviato/library/zizmor.yml tests/core/test_zizmor_config.py
git commit -m "feat: pin zizmor dependency + bundle uses/image pin policy config (§11.3)"
```

---

### Task 2: zizmor wrapper plugin (parse JSON, filter to gated audits)

**Files:**
- Create: `aviato/plugins/zizmor_scan.py`
- Test: `tests/core/test_zizmor_scan.py`

- [ ] **Step 1: Write the failing test (parser, with zizmor stubbed)**

```python
# tests/core/test_zizmor_scan.py
import json
import subprocess

import pytest

from aviato.plugins import zizmor_scan


def _fake_run(stdout: str, returncode: int = 0):
    def _run(command, *, cwd=None, check=True):
        return subprocess.CompletedProcess(command, returncode, stdout, "")
    return _run


def test_filters_to_gated_audits_only(tmp_path, monkeypatch):
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    findings = json.dumps([
        {"ident": "unpinned-uses", "locations": [{"symbolic": {"key": {"Local": {"given_path": "w.yml"}}}}]},
        {"ident": "template-injection", "locations": [{"symbolic": {"key": {"Local": {"given_path": "w.yml"}}}}]},
    ])
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run(findings))
    out = zizmor_scan.zizmor_uses_image_violations(tmp_path)
    assert any("unpinned-uses" in v for v in out)
    assert not any("template-injection" in v for v in out)  # non-gated audit ignored


def test_empty_when_no_findings(tmp_path, monkeypatch):
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run("[]\n", 0))
    assert zizmor_scan.zizmor_uses_image_violations(tmp_path) == []


def test_absent_workflow_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    assert zizmor_scan.zizmor_uses_image_violations(tmp_path / "nope") == []


def test_raises_when_zizmor_missing(tmp_path, monkeypatch):
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: False)
    with pytest.raises(zizmor_scan.ZizmorUnavailable):
        zizmor_scan.zizmor_uses_image_violations(tmp_path)


def test_raises_on_zizmor_error_exit(tmp_path, monkeypatch):
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run("", 1))  # 1 = audit error
    with pytest.raises(zizmor_scan.ZizmorUnavailable):
        zizmor_scan.zizmor_uses_image_violations(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/core/test_zizmor_scan.py -v`
Expected: FAIL (`No module named 'aviato.plugins.zizmor_scan'`).

- [ ] **Step 3: Write the wrapper**

```python
# aviato/plugins/zizmor_scan.py
"""Run the pinned zizmor (§11.3) and surface only the GATED audits as violations.

Lives in plugins (NOT core): it names a concrete tool, so it would trip the §9b denylist if
placed in aviato/core. The bundled config (aviato/library/zizmor.yml) carries the pin policy.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..command import run
from ..paths import POLICY_DATA_ROOT

ZIZMOR_CONFIG = POLICY_DATA_ROOT / "zizmor.yml"

# Audits aviato gates on today. zizmor runs all audits; we surface only these. Forward-compatible:
# adopting another audit is a one-line addition here (plus a doc note), not a new detector.
_GATED_AUDITS = frozenset({"unpinned-uses", "unpinned-images"})


class ZizmorUnavailable(RuntimeError):
    """zizmor is not installed or failed to run — fail closed (never report 'clean')."""


def _zizmor_available() -> bool:
    return shutil.which("zizmor") is not None


def _finding_location(finding: dict) -> str:
    """Best-effort 'file' string from a zizmor JSON finding (schema-tolerant).

    Real shape verified against zizmor 1.25.2:
    locations[i]["symbolic"]["key"]["Local"]["given_path"].
    """
    for loc in finding.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        key = (loc.get("symbolic") or {}).get("key")
        local = key.get("Local") if isinstance(key, dict) else None
        if isinstance(local, dict):
            name = local.get("given_path") or local.get("prefix")
            if name:
                return str(name)
    return finding.get("ident", "?")


def zizmor_uses_image_violations(workflow_dir: Path) -> list[str]:
    """Return gated zizmor findings for ``workflow_dir`` as ``ident: file`` strings.

    Empty if the directory is absent. Raises :class:`ZizmorUnavailable` if zizmor is missing or
    errors (§5.14: an unrunnable gate reads as broken, never silently clean).
    """
    workflow_dir = Path(workflow_dir)
    if not workflow_dir.is_dir():
        return []
    if not _zizmor_available():
        raise ZizmorUnavailable(
            "zizmor is not on PATH; it is a pinned dependency of aviato (pip install aviato)"
        )
    # --no-exit-codes: findings no longer set exit 11-14, so a non-zero code means a real ERROR
    # (1 audit error / 2 argparse / 3 no inputs). We detect findings from the JSON, not the code.
    result = run(
        [
            "zizmor",
            "--config",
            str(ZIZMOR_CONFIG),
            "--format",
            "json",
            "--no-exit-codes",
            str(workflow_dir),
        ],
        check=False,
    )
    if result.returncode == 3:  # no inputs collected (no workflows) — clean
        return []
    if result.returncode != 0:
        raise ZizmorUnavailable(f"zizmor failed (exit {result.returncode}): {result.stderr.strip()}")
    if not result.stdout.strip():
        return []
    try:
        findings = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ZizmorUnavailable(f"could not parse zizmor JSON output: {exc}") from exc
    violations = {
        f"{f.get('ident')}: {_finding_location(f)}"
        for f in findings
        if isinstance(f, dict) and f.get("ident") in _GATED_AUDITS
    }
    return sorted(violations)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/core/test_zizmor_scan.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Add a real-zizmor integration test (locks the JSON contract)**

Append to `tests/core/test_zizmor_scan.py`:

```python
import shutil as _shutil


@pytest.mark.skipif(_shutil.which("zizmor") is None, reason="zizmor not installed")
def test_real_zizmor_flags_unpinned_and_passes_first_party(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "bad.yml").write_text(
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"            # actions/* ref-pin -> OK
        "      - uses: docker/build-push-action@v5\n",   # third-party tag -> FLAG
        encoding="utf-8",
    )
    out = zizmor_scan.zizmor_uses_image_violations(wf)
    assert any("unpinned-uses" in v for v in out), out
```

- [ ] **Step 6: Run it (and the file)**

Run: `python3 -m pytest tests/core/test_zizmor_scan.py -v`
Expected: PASS. If the real-zizmor test reveals the JSON `ident`/`locations` field names differ from `_finding_location`'s assumptions, adjust `_finding_location` to match the actual output, then re-run until green.

- [ ] **Step 7: Commit**

```bash
git add aviato/plugins/zizmor_scan.py tests/core/test_zizmor_scan.py
git commit -m "feat: zizmor wrapper — gate on unpinned-uses/unpinned-images, fail closed if absent"
```

---

### Task 3: Fail-closed fetch-execute check (replace the interpreter-enumeration machinery)

**Files:**
- Modify: `aviato/plugins/actionpins.py` (add `_fold_logical_lines`, `fetch_execute_violations`; will delete old machinery in Task 4)
- Test: `tests/core/test_fetch_execute.py`

- [ ] **Step 1: Write the failing test (the fail-closed contract)**

```python
# tests/core/test_fetch_execute.py
from aviato.plugins.actionpins import fetch_execute_violations as fev


# All of these executed fetched bytes and were MISSED by the old fail-open detector (cycle-9
# R9-1..R9-4) — fail-closed must FLAG every one.
FLAGGED = [
    "curl -fsSL https://x/i.sh | bash",
    "curl -fsSL https://x/i.sh | sudo bash",
    'bash -c "$(curl -fsSL https://x/i.sh)"',
    "bash <(curl -fsSL https://x/i.sh)",
    'eval "$(curl -fsSL https://x/i.sh)"',
    ". <(curl -fsSL https://x/i.sh)",
    "B=/bin/bash; curl -fsSL https://x/i.sh | $B",
    "wget -qO- https://x/i.sh | python3",
]

# Safe: integrity proven (checksum) or an allowlisted non-executing data sink. Must NOT flag.
ALLOWED = [
    "curl -fsSL https://x/i.sh -o f && sha256sum -c sums.txt && bash f",
    "curl -fsSL https://x/v.json | jq .version",
    "curl -fsSL https://x/r.txt | grep tag_name",
    "curl -fsSL https://x/f | tee out.log",
    "curl -fsSL https://x/f -o out.bin",            # no pipe/subst at all
    "cosign verify ... && curl https://x | bash",   # verification present
]


def test_failclosed_flags_all_fetch_execute():
    for line in FLAGGED:
        assert fev(line), f"fail-open miss: {line}"


def test_failclosed_allows_verified_and_data_sinks():
    for line in ALLOWED:
        assert fev(line) == [], f"false positive: {line}"


def test_yaml_folded_pipeline_is_one_logical_line():
    # `curl ... |` + next line `bash`  AND  `curl ...` + next line `| bash`
    assert fev("curl -fsSL https://x/i.sh |\n  bash\n")
    assert fev("curl -fsSL https://x/i.sh\n  | bash\n")


def test_backslash_continuation_folded():
    assert fev("curl -fsSL https://x/i.sh \\\n  | bash\n")


def test_comment_lines_ignored():
    assert fev("# curl https://x | bash  (just docs)\n") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/core/test_fetch_execute.py -v`
Expected: FAIL (`cannot import name 'fetch_execute_violations'`).

- [ ] **Step 3: Add the fail-closed implementation to `actionpins.py`**

Add near the top (after the existing imports / `_FETCH_CMD_RE`):

```python
# §11.3 FAIL-CLOSED fetch-execute detection. DO NOT convert this back to interpreter enumeration:
# that approach fails OPEN (an unknown interpreter/wrapper = a miss) and flapped for 8 commits
# (cycle-9 findings R9-1..R9-5). Here the DEFAULT for anything not provably safe is REJECT.
_FETCH_RE = re.compile(r"\b(?:curl|wget)\b")
# A substitution that can execute fetched output: process-sub `<(`/`>(`, command-sub `$(`, backtick.
_SUBST_RE = re.compile(r"<\(|>\(|\$\(|`")
# Proof of integrity on the same logical line → allowed.
_CHECKSUM_RE = re.compile(r"\b(?:sha256sum|sha512sum|shasum|md5sum|cosign|gpg)\b")
# The ONLY downstream pipe targets that pass WITHOUT a checksum: non-executing data sinks.
# Intentionally minimal (spec §3.4); add a tool here only after confirming it cannot execute its
# stdin. NOT included on purpose: awk/sed (can `-f -`), xargs, any shell.
_ALLOWED_SINKS = frozenset({"jq", "grep", "tee", "cat", "sort", "uniq", "head", "tail", "wc"})


def _fold_logical_lines(text: str) -> list[str]:
    """Fold shell `\\`-newline continuations and split-pipe YAML scalars into logical lines.

    Folding only ever JOINS lines, so it can add flags, never remove them (fail-closed safe). It
    handles the common multi-line pipeline forms a physical-line scan misses (cycle-9 R9-2):
    a pipe at end-of-line (`curl … |⏎ bash`) and a pipe at start-of-next-line (`curl …⏎ | bash`).
    """
    text = re.sub(r"\\\n[ \t]*", " ", text)        # shell line-continuation
    text = re.sub(r"\|[ \t]*\n[ \t]*", "| ", text)  # pipe at EOL → join with next
    text = re.sub(r"\n[ \t]*\|", " |", text)        # pipe leads next line → join with prev
    return text.splitlines()


def _pipe_targets_all_allowlisted(line: str) -> bool:
    """True iff EVERY command downstream of a `|` is a known non-executing data sink."""
    for segment in line.split("|")[1:]:
        tokens = segment.split()
        if not tokens:
            return False
        first = tokens[0].rsplit("/", 1)[-1]  # basename, so /usr/bin/jq → jq
        if first not in _ALLOWED_SINKS:
            return False
    return True


def fetch_execute_violations(text: str) -> list[str]:
    """Fail-closed §11.3 fetch-execute check.

    A logical line containing curl/wget AND a pipe-into-command or executing substitution is a
    violation UNLESS it proves safety: a checksum/verify token on the line, OR (pipe-only, no
    substitution) every downstream pipe target is an allowlisted data sink. Anything the rule does
    not positively recognize as safe is flagged.
    """
    violations: list[str] = []
    for line in _fold_logical_lines(text):
        if line.lstrip().startswith("#"):
            continue
        if not _FETCH_RE.search(line):
            continue
        has_subst = bool(_SUBST_RE.search(line))
        has_pipe = "|" in line
        if not (has_subst or has_pipe):
            continue  # a bare fetch (curl … -o file) is fine
        if _CHECKSUM_RE.search(line):
            continue  # operator proved integrity
        if has_pipe and not has_subst and _pipe_targets_all_allowlisted(line):
            continue  # piped only into non-executing data sinks
        violations.append(f"fetch-and-execute without checksum: {line.strip()}")
    return violations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/core/test_fetch_execute.py -v`
Expected: PASS (all). If `test_failclosed_allows...` fails on the `cosign verify ... && curl | bash` case, that's expected behavior tension — keep that line in ALLOWED only if a checksum token is present; it is (`cosign`), so it passes.

- [ ] **Step 5: Commit**

```bash
git add aviato/plugins/actionpins.py tests/core/test_fetch_execute.py
git commit -m "feat: fail-closed fetch-execute check (replaces interpreter enumeration)"
```

---

### Task 4: Rewire `action_pin_violations` (zizmor + fetch + pip + scaffold-uses); delete old machinery

**Files:**
- Modify: `aviato/plugins/actionpins.py`
- Test: `tests/core/test_actionpins.py` (rewrite)

- [ ] **Step 1: Rewrite `unpinned_tool_invocations` to fetch+pip only (drop docker)**

Replace the entire body of `unpinned_tool_invocations` with:

```python
def unpinned_tool_invocations(text: str) -> list[str]:
    """Shell-invoked tools not pinned (§11.3): fail-closed fetch-execute + non-exact pip installs.

    Container-image pinning (`container:`/`services:`) is handled by zizmor's `unpinned-images`;
    ad-hoc `docker run img:tag` inside a shell `run:` block is intentionally no longer gated
    (see REQUIREMENTS §11.3 scope note).
    """
    no_comments = "\n".join(
        line for line in "\n".join(_fold_logical_lines(text)).splitlines()
        if not line.lstrip().startswith("#")
    )
    violations: list[str] = list(fetch_execute_violations(no_comments))
    for match in _PIP_INSTALL_RE.finditer(no_comments):
        for pkg in _unpinned_pip_packages(match.group("rest")):
            violations.append(f"pip-installed tool not pinned to an exact version: {pkg}")
    return violations
```

- [ ] **Step 2: Rewrite `action_pin_violations` to compose zizmor + Python checks**

Replace the entire `action_pin_violations` function with:

```python
def action_pin_violations(root: Path) -> list[str]:
    """Scan a repo's workflows + scaffold bodies for §11.3 violations.

    Real `.github/workflows/` get zizmor (`unpinned-uses`/`unpinned-images`) for action/image
    pinning. Scaffold template bodies (`wf-*.yml`, carrying `{{ aviato-ref }}` placeholders zizmor
    cannot parse) get a placeholder-aware `uses:` SHA check. Both get the fail-closed fetch-execute
    + pip checks. Seeded requirements files get the exact-pin check.
    """
    from .zizmor_scan import ZizmorUnavailable, zizmor_uses_image_violations

    root = Path(root)
    workflow_dir = root / ".github" / "workflows"
    scaffold_dir = root / "aviato" / "library" / "scaffold" / "files"
    violations: list[str] = []

    # 1. zizmor on real workflows (uses + images).
    try:
        for v in zizmor_uses_image_violations(workflow_dir):
            violations.append(f".github/workflows: {v}")
    except ZizmorUnavailable as exc:
        violations.append(f"zizmor unavailable (cannot verify action/image pins, §5.14): {exc}")

    # 2. Fetch-execute + pip checks on real workflows.
    workflow_files = sorted(p for ext in ("*.yml", "*.yaml") for p in workflow_dir.glob(ext))
    for path in workflow_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for tool in unpinned_tool_invocations(text):
            violations.append(f"{path.name}: {tool}")

    # 3. Scaffold bodies: placeholder-aware uses: + fetch + pip (zizmor can't parse templates).
    scaffold_files = sorted(p for ext in ("wf-*.yml", "wf-*.yaml") for p in scaffold_dir.glob(ext))
    for path in scaffold_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for ref in unpinned_third_party_uses(text):
            if "{{" in ref:  # scaffold placeholder, resolved at scaffold time
                continue
            violations.append(f"{path.name}: {ref}")
        for tool in unpinned_tool_invocations(text):
            violations.append(f"{path.name}: {tool}")

    # 4. Seeded requirements files (installed by CI; floors are invisible to the pip-install scan).
    for req in sorted(scaffold_dir.glob("requirements*.txt.txt")):
        for pkg in unpinned_requirements_lines(req.read_text(encoding="utf-8", errors="replace")):
            violations.append(f"{req.name}: requirement not pinned to an exact version: {pkg}")
    return violations
```

- [ ] **Step 3: Delete the dead machinery**

Remove these symbols from `actionpins.py` entirely (they are no longer referenced):
`_DOCKER_RUN_RE`, `_docker_run_image`, `_DOCKER_VALUE_FLAGS`, `_fetch_pipe_violation`,
`_first_executed_command`, `_tokenize_segment`, `_balanced_paren_bodies`,
`_inner_execution_is_interpreter`, `_INTERPRETERS`, `_PYTHON_INTERP_RE`, `_FETCH_WRAPPERS_SET`,
`_WRAPPERS_WITH_POSITIONAL_ARG`, `_WRAPPERS_REQUIRING_RUN`, `_INLINE_ASSIGN_RE`,
`_TIMEOUT_DURATION_RE`, `_PROCSUB_RE`, `_CMDSUB_PAREN_RE`, `_CMDSUB_BACKTICK_RE`,
`_basename_if_absolute`, `_token_is_interpreter`, `_token_is_wrapper`, `_LINT_DEFINITION_FILE`.
Keep: `_FIRST_PARTY_OWNERS`, `_LIBRARY_*`, `_USES_RE`, `_SHA_RE`, `_is_third_party`,
`unpinned_third_party_uses`, `_FETCH_CMD_RE` (now used only by `fetch_execute_violations` via
`_FETCH_RE` — actually delete `_FETCH_CMD_RE` too if unused), `_PIP_*`, `_unpinned_pip_packages`,
`unpinned_requirements_lines`, and the new fail-closed block from Task 3.

- [ ] **Step 4: Run ruff to confirm no dangling references**

Run: `ruff check aviato/plugins/actionpins.py`
Expected: PASS (no F811/F821/unused-import). Fix any unused leftover (`shlex` import is now unused — remove it).

- [ ] **Step 5: Rewrite the test file `tests/core/test_actionpins.py`**

Replace it wholesale with the focused suite below (the old fetch-pipe TP/FP corpus, docker-token, and grep-parity tests are obsolete and removed):

```python
from pathlib import Path

from aviato.plugins.actionpins import (
    action_pin_violations,
    unpinned_requirements_lines,
    unpinned_third_party_uses,
    unpinned_tool_invocations,
)

_SHA = "a" * 40


# --- uses: SHA check (kept for scaffold bodies; placeholder-aware in action_pin_violations) ---

def test_flags_third_party_mutable_tag():
    assert unpinned_third_party_uses("      - uses: docker/build-push-action@v5\n") == [
        "docker/build-push-action@v5"
    ]


def test_third_party_pinned_to_sha_is_ok():
    assert unpinned_third_party_uses(f"      - uses: a/b@{_SHA}\n") == []


def test_first_party_and_library_self_ref_exempt():
    assert unpinned_third_party_uses("      - uses: actions/checkout@v4\n") == []
    assert unpinned_third_party_uses(
        "      - uses: amattas/aviato/.github/workflows/x.yml@v1\n"
    ) == []


def test_uses_with_space_before_colon_still_checked():
    assert unpinned_third_party_uses("      - uses : third/action@main\n") == ["third/action@main"]


# --- pip exact-version (kept) ---

def test_flags_floating_pip_install():
    out = unpinned_tool_invocations("          pip install build pytest>=8\n")
    assert "build" in str(out) and "pytest>=8" in str(out)


def test_exact_pip_pin_is_ok():
    assert unpinned_tool_invocations(f"          pip install build==1.2.3\n") == []


def test_pip_local_vcs_wheel_requirements_skipped():
    text = "          pip install . -e ./pkg -r reqs.txt git+https://x dist/a.whl\n"
    assert unpinned_tool_invocations(text) == []


def test_unpinned_requirements_lines_flags_floors_not_exact():
    body = "pytest>=8.0\nruff==0.8.0\n# comment\nbuild\n"
    flagged = unpinned_requirements_lines(body)
    assert "pytest>=8.0" in flagged and "build" in flagged and "ruff==0.8.0" not in flagged


# --- end-to-end (zizmor stubbed so the unit suite is hermetic) ---

def test_action_pin_scan_flags_floor_seeded_requirements(tmp_path, monkeypatch):
    from aviato.plugins import zizmor_scan
    monkeypatch.setattr(zizmor_scan, "zizmor_uses_image_violations", lambda _d: [])
    seed = tmp_path / "aviato" / "library" / "scaffold" / "files"
    seed.mkdir(parents=True)
    (seed / "requirements-dev.txt.txt").write_text("pytest>=8.0\n", encoding="utf-8")
    out = action_pin_violations(tmp_path)
    assert any("pytest>=8.0" in v for v in out)


def test_action_pin_scan_flags_fetch_execute_in_workflow(tmp_path, monkeypatch):
    from aviato.plugins import zizmor_scan
    monkeypatch.setattr(zizmor_scan, "zizmor_uses_image_violations", lambda _d: [])
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("        run: curl https://x/i.sh | bash\n", encoding="utf-8")
    out = action_pin_violations(tmp_path)
    assert any("fetch-and-execute" in v for v in out)


def test_action_pin_scan_surfaces_zizmor_uses_finding(tmp_path, monkeypatch):
    from aviato.plugins import zizmor_scan
    monkeypatch.setattr(
        zizmor_scan, "zizmor_uses_image_violations", lambda _d: ["unpinned-uses: ci.yml"]
    )
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push\n", encoding="utf-8")
    out = action_pin_violations(tmp_path)
    assert any("unpinned-uses" in v for v in out)


def test_action_pin_scan_tolerates_non_utf8_workflow(tmp_path, monkeypatch):
    from aviato.plugins import zizmor_scan
    monkeypatch.setattr(zizmor_scan, "zizmor_uses_image_violations", lambda _d: [])
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "bad.yml").write_bytes(b"\xff\xfe not utf8")
    action_pin_violations(tmp_path)  # must not raise
```

- [ ] **Step 6: Run the suite**

Run: `python3 -m pytest tests/core/test_actionpins.py tests/core/test_fetch_execute.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add aviato/plugins/actionpins.py tests/core/test_actionpins.py
git commit -m "refactor: action_pin_violations = zizmor + fail-closed fetch + pip; delete enumeration machinery"
```

---

### Task 5: Replace the in-CI grep mirror with `aviato lint-actions`

**Files:**
- Modify: `.github/workflows/reusable-common-lint.yml`
- Test: `tests/test_workflow_guards.py`

- [ ] **Step 1: Update the workflow-guard tests**

In `tests/test_workflow_guards.py`: DELETE `test_cilint_interps_mirror_actionpins` entirely. Add:

```python
def test_common_lint_runs_aviato_lint_actions_not_grep() -> None:
    wf = (WORKFLOWS / "reusable-common-lint.yml").read_text(encoding="utf-8")
    assert "aviato lint-actions" in wf, "common-lint must run the single aviato lint-actions impl"
    assert "interps=" not in wf, "the grep mirror must be gone (parity flap removed)"
    assert "docker[[:space:]]+(run|pull)" not in wf, "the docker grep extractor must be gone"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_workflow_guards.py::test_common_lint_runs_aviato_lint_actions_not_grep -v`
Expected: FAIL (`interps=` still present).

- [ ] **Step 3: Edit `reusable-common-lint.yml`**

Delete both steps named **"Third-party action digest pin (blocking)"** and **"Container image + fetched-binary pin (blocking)"** (lines ~66–171). Replace them with a single step:

```yaml
      # §11.3 (blocking): one implementation, shared with `aviato validate`. Installs aviato from
      # THIS reusable workflow's own pinned ref (so the linter matches the pinned policy) and runs
      # the single detector — zizmor (unpinned-uses/unpinned-images) + fail-closed fetch-execute +
      # pip exact-version. Replaces the former grep mirror (which drifted from the Python detector).
      - name: Supply-chain pins (blocking)
        shell: bash
        run: |
          set -euo pipefail
          if [ ! -d .github/workflows ]; then
            echo "No workflows to check."; exit 0
          fi
          python -m pip install --quiet "aviato @ git+https://github.com/${GITHUB_ACTION_REPOSITORY}@${GITHUB_ACTION_REF}"
          aviato lint-actions .
```

- [ ] **Step 4: Run actionlint on the edited workflow**

Run: `actionlint .github/workflows/reusable-common-lint.yml`
Expected: no errors. (If actionlint flags `GITHUB_ACTION_REPOSITORY`/`GITHUB_ACTION_REF` as possibly-unset, that is acceptable — they are always set inside a reusable workflow; otherwise hardcode `amattas/aviato`.)

- [ ] **Step 5: Run the guard test**

Run: `python3 -m pytest tests/test_workflow_guards.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/reusable-common-lint.yml tests/test_workflow_guards.py
git commit -m "feat: in-CI gate runs aviato lint-actions (single impl); delete grep mirror (R9-5)"
```

---

### Task 6: `aviato validate` + `lint-actions` CLI wiring

**Files:**
- Modify: `aviato/cli.py` (`cmd_lint_actions` — handle ZizmorUnavailable cleanly)
- Modify: `aviato/validation.py` (no logic change to `_check_action_pins`; verify it still composes)
- Test: `tests/test_cli_lint_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_lint_actions.py
from aviato.cli import cmd_lint_actions
import argparse


def test_lint_actions_exit2_when_zizmor_missing(tmp_path, monkeypatch, capsys):
    from aviato.plugins import zizmor_scan
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: False)
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push\n", encoding="utf-8")
    rc = cmd_lint_actions(argparse.Namespace(path=str(tmp_path)))
    assert rc == 1  # a violation row ("zizmor unavailable…") → exit 1, never silent 0
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python3 -m pytest tests/test_cli_lint_actions.py -v`
Expected: PASS already if `action_pin_violations` appends the "zizmor unavailable" row (Task 4 Step 2) and `cmd_lint_actions` returns 1 on any violation. If it errors instead, proceed to Step 3.

- [ ] **Step 3: Confirm `cmd_lint_actions` message still fits (no code change expected)**

`cmd_lint_actions` (cli.py:1437) already prints each violation and returns 1 if any. The "zizmor unavailable" string is one such violation row, so it surfaces and exits 1. No change needed. (If you want a distinct exit-2 for environment errors, that is optional and out of scope.)

- [ ] **Step 4: Run the full actionpins + validate-adjacent tests**

Run: `python3 -m pytest tests/test_cli_lint_actions.py tests/core/test_actionpins.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli_lint_actions.py
git commit -m "test: lint-actions surfaces zizmor-unavailable as a failing violation (fail closed)"
```

---

### Task 7: Run `aviato validate` end-to-end on the Library itself

**Files:** none (verification task)

- [ ] **Step 1: Run validate against the repo**

Run: `python3 -m aviato.cli validate`
Expected: passes. The Library's own workflows use `actions/*@vN` (ref-pin OK) and pinned third-party SHAs; scaffold bodies use `{{ aviato-ref }}` (skipped). If zizmor flags a real unpinned third-party action in the repo, FIX the workflow (pin to SHA) — that is a true finding, not a test problem.

- [ ] **Step 2: Run `aviato lint-actions .` directly**

Run: `python3 -m aviato.cli lint-actions .`
Expected: "All third-party actions are digest-pinned." (or a real finding to fix).

- [ ] **Step 3: Commit any workflow pin fixes**

```bash
git add .github/workflows
git commit -m "chore: pin any third-party actions flagged by zizmor under the new gate"
```
(Skip if nothing changed.)

---

### Task 8: Docs (anti-flap — record the fail-closed decision + scope change)

**Files:**
- Modify: `REQUIREMENTS.md` (§11.3)
- Modify: `CLAUDE.md` (actionpins section)
- Modify: `ARCHITECTURE.md`

- [ ] **Step 1: REQUIREMENTS.md §11.3** — add a paragraph:

> §11.3 enforcement is delegated/fail-closed. Action and container-image pinning are enforced by
> **zizmor** (`unpinned-uses`, `unpinned-images`) via a bundled policy config. Fetch-execute
> (`curl|bash`) detection is **fail-closed**: it does NOT enumerate interpreters — any `curl`/`wget`
> piped or substituted is rejected unless integrity is proven (a checksum/verify on the line) or the
> output flows only into an allowlisted non-executing sink (`jq`/`grep`/`tee`→file). **Do not
> re-introduce interpreter enumeration; it fails open and flapped for 8 cycles (cycle-9 R9-1..R9-5).**
> Scope: `docker run img:tag` inside a shell `run:` block is intentionally NOT gated (use a
> `container:` image, which zizmor pins, or pin in the Dockerfile).

- [ ] **Step 2: CLAUDE.md** — replace the `aviato/plugins/actionpins.py` / "GitHub access" detector description and the `_check_action_pins` line to state: zizmor (bundled `aviato/library/zizmor.yml`) handles `uses:`/images; `aviato lint-actions` is the single impl run by CI and `aviato validate`; the in-CI grep mirror is gone; fetch-execute is fail-closed. Remove any mention of the `interps=` grep parity / `_INTERPRETERS`.

- [ ] **Step 3: ARCHITECTURE.md** — note zizmor as the pinned action/image-pinning engine and `aviato/library/zizmor.yml` as policy data shipped in the wheel.

- [ ] **Step 4: Commit**

```bash
git add REQUIREMENTS.md CLAUDE.md ARCHITECTURE.md
git commit -m "docs: record fail-closed fetch policy + zizmor delegation (anti-flap, §11.3)"
```

---

### Task 9: Full gate

**Files:** none (verification)

- [ ] **Step 1: Run the strict gate**

Run: `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh`
Expected: compile + validate + ruff + pytest + shellcheck + actionlint all green; no skipped-tool banner. Fix any fallout (most likely: ruff unused-import in actionpins.py; a stale reference in another test).

- [ ] **Step 2: Confirm the LOC reduction**

Run: `git diff --stat <first-task-commit>^..HEAD -- aviato/plugins/actionpins.py tests/core/test_actionpins.py`
Expected: net deletion in the hundreds of lines (the enumeration machinery + obsolete corpus).

- [ ] **Step 3: Final commit (if any gate fixes)**

```bash
git add -A
git commit -m "chore: green the strict gate after zizmor migration"
```

---

## Self-review notes
- **Spec coverage:** §3.1 (Task 4/5/6), §3.2 zizmor+config (Task 1/2), §3.3 scaffold (Task 4), §3.4 fail-closed (Task 3), §3.5 pip kept (Task 4 tests), §3.6 CI (Task 5), §3.7 validate (Task 6/7), §5 docs (Task 8), §6 tests (Tasks 2-6), §9 acceptance (Task 9). Covered.
- **Type consistency:** `zizmor_uses_image_violations(Path) -> list[str]`, `fetch_execute_violations(str) -> list[str]`, `unpinned_tool_invocations(str) -> list[str]`, `action_pin_violations(Path) -> list[str]`, `ZizmorUnavailable` — names used identically across Tasks 2/3/4/6.
- **Open risk carried into execution:** zizmor JSON field names for `_finding_location` (Task 2 Step 6 verifies against real output and adjusts). Version pin resolved: PyPI latest stable is `1.25.2` (verified reachable), pinned in Task 1.
