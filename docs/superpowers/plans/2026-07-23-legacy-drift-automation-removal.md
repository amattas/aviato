# Legacy Drift Automation Removal Implementation Plan (Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the scheduled consumer drift automation and `drift-report` CLI from the aviato library, and repoint `doctor`/`scan` health checks at the bot's `/api/repo-status` endpoint.

**Architecture:** Add a small stdlib-only HTTP probe module (`aviato/botstatus.py`), swap it into `doctor`/`scan` in place of the drift-workflow probe, then delete the `drift-report` command, both workflow files, the `wf-drift` scaffold artifact, and every validation expectation that references them. The shared settings-read token plumbing (`settings_read_token_scope`, `AVIATO_SETTINGS_READ_TOKEN`) **stays** — `probe_health()` uses it for doctor/scan settings reads (verified: `aviato/github_platform.py:643`).

**Tech Stack:** Python 3.12, argparse CLI, pytest, stdlib `urllib.request` (no new deps).

**Spec:** `../aviato-bot/docs/superpowers/specs/2026-07-23-bot-drift-automation-and-legacy-removal-design.md`

**Precondition:** Plan A is implemented and deployed — the bot serves `GET /api/repo-status?repo=owner/name` with bearer auth (contract in Plan A Task 5).

## Global Constraints

- Run tests as `pytest -q`; run the repo's CI-parity gate (`./validate.sh` — check README for the exact invocation) before declaring done.
- TDD: failing test first; parameterize instead of sibling tests.
- No new dependencies; the probe uses `urllib.request`.
- Env vars for the probe: `AVIATO_BOT_URL` (base URL) + `AVIATO_BOT_STATUS_TOKEN` (bearer token) — same names the bot's deploy docs use.
- Keep `aviato/core/drift` untouched: the bot imports `run_file_drift` / `run_settings_drift` machinery from it.
- Version bump at the end per Conventional Commits (0.6.1 → 0.7.0: features + pre-1.0 breaking removals).
- Commit after each task.

---

### Task 1: Bot status probe module

**Files:**
- Create: `aviato/botstatus.py`
- Test: `tests/test_botstatus.py`

**Interfaces:**
- Consumes: env vars `AVIATO_BOT_URL`, `AVIATO_BOT_STATUS_TOKEN`; the bot endpoint contract — 200 `{"managed": true, "repo": str, "drift": [{"kind","status","detail","updated_at"}]}`, 404 unmanaged, 401 bad token.
- Produces: `probe_bot_status(repo: str, *, opener=None) -> BotStatus` where `BotStatus` is the frozen dataclass below. Tasks 2–3 consume exactly this.

- [ ] **Step 1: Write the failing tests** — create `tests/test_botstatus.py`:

```python
"""Bot repo-status probe: configured/unconfigured, covered/uncovered, and error paths."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from aviato.botstatus import BotStatus, probe_bot_status


def _opener_returning(payload: dict) -> object:
    class _Response(io.BytesIO):
        status = 200

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args):  # noqa: ANN002, ANN204
            return False

    def opener(request, timeout):  # noqa: ANN001, ANN202
        assert request.get_header("Authorization") == "Bearer tok"
        return _Response(json.dumps(payload).encode())

    return opener


def _opener_raising(exc: Exception) -> object:
    def opener(request, timeout):  # noqa: ANN001, ANN202
        raise exc

    return opener


def test_unconfigured_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AVIATO_BOT_URL", raising=False)
    monkeypatch.delenv("AVIATO_BOT_STATUS_TOKEN", raising=False)
    status = probe_bot_status("acme/app")
    assert status == BotStatus(configured=False, covered=None, last_checked=None, error=None)


@pytest.mark.parametrize(
    ("payload", "expected_covered", "expected_last"),
    [
        (
            {
                "managed": True,
                "repo": "acme/app",
                "drift": [
                    {"kind": "settings", "status": "clean", "detail": None, "updated_at": "2026-07-20T06:17:00+00:00"},
                    {"kind": "file", "status": "drift", "detail": None, "updated_at": "2026-07-22T06:17:00+00:00"},
                ],
            },
            True,
            "2026-07-22T06:17:00+00:00",
        ),
        ({"managed": True, "repo": "acme/app", "drift": []}, True, None),
    ],
)
def test_covered_repo_reports_latest_check(
    monkeypatch: pytest.MonkeyPatch, payload: dict, expected_covered: bool, expected_last: str | None
) -> None:
    monkeypatch.setenv("AVIATO_BOT_URL", "https://bot.example")
    monkeypatch.setenv("AVIATO_BOT_STATUS_TOKEN", "tok")
    status = probe_bot_status("acme/app", opener=_opener_returning(payload))
    assert status.configured and status.covered is expected_covered
    assert status.last_checked == expected_last
    assert status.error is None


@pytest.mark.parametrize(
    ("exc", "expected_covered", "error_contains"),
    [
        (urllib.error.HTTPError("u", 404, "nf", {}, None), False, None),
        (urllib.error.HTTPError("u", 401, "bad", {}, None), None, "401"),
        (urllib.error.URLError("refused"), None, "refused"),
    ],
)
def test_error_paths(
    monkeypatch: pytest.MonkeyPatch, exc: Exception, expected_covered: bool | None, error_contains: str | None
) -> None:
    monkeypatch.setenv("AVIATO_BOT_URL", "https://bot.example")
    monkeypatch.setenv("AVIATO_BOT_STATUS_TOKEN", "tok")
    status = probe_bot_status("acme/app", opener=_opener_raising(exc))
    assert status.configured
    assert status.covered is expected_covered
    if error_contains is None:
        assert status.error is None
    else:
        assert error_contains in (status.error or "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_botstatus.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'aviato.botstatus'`.

- [ ] **Step 3: Implement** — create `aviato/botstatus.py`:

```python
"""Probe the aviato-bot repo-status endpoint (the drift-automation heartbeat, §17).

Replaces the retired scheduled-workflow heartbeat: the bot is now the drift detector,
so doctor/scan ask it directly whether a repo is covered and when drift last ran.
Read-only; stdlib-only so the CLI gains no dependency.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

BOT_URL_ENV = "AVIATO_BOT_URL"
BOT_STATUS_TOKEN_ENV = "AVIATO_BOT_STATUS_TOKEN"
_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class BotStatus:
    """The tri-state heartbeat: unconfigured, covered/uncovered, or probe failure."""

    configured: bool
    covered: bool | None  # None: unconfigured or the probe failed
    last_checked: str | None  # latest drift updated_at (ISO-8601), when covered
    error: str | None


def probe_bot_status(repo: str, *, opener=None) -> BotStatus:
    base_url = os.environ.get(BOT_URL_ENV, "").rstrip("/")
    token = os.environ.get(BOT_STATUS_TOKEN_ENV, "")
    if not base_url or not token:
        return BotStatus(configured=False, covered=None, last_checked=None, error=None)
    query = urllib.parse.urlencode({"repo": repo})
    request = urllib.request.Request(
        f"{base_url}/api/repo-status?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return BotStatus(configured=True, covered=False, last_checked=None, error=None)
        return BotStatus(
            configured=True, covered=None, last_checked=None, error=f"bot status probe failed: HTTP {exc.code}"
        )
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return BotStatus(configured=True, covered=None, last_checked=None, error=f"bot status probe failed: {exc}")
    drift = payload.get("drift") if isinstance(payload, dict) else None
    timestamps = sorted(
        row.get("updated_at")
        for row in (drift or [])
        if isinstance(row, dict) and isinstance(row.get("updated_at"), str)
    )
    return BotStatus(
        configured=True,
        covered=bool(payload.get("managed")) if isinstance(payload, dict) else None,
        last_checked=timestamps[-1] if timestamps else None,
        error=None,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest -q tests/test_botstatus.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add aviato/botstatus.py tests/test_botstatus.py
git commit -m "feat: add bot repo-status heartbeat probe"
```

---

### Task 2: Repoint doctor at the bot probe

**Files:**
- Modify: `aviato/core/diagnosis.py` (DiagnosisReport, lines 26-44), `aviato/cli.py` (`cmd_doctor`, ~968-1054), `aviato/github_platform.py` (`probe_health`, 608-799)
- Test: `tests/test_cli_doctor.py`

**Interfaces:**
- Consumes: `probe_bot_status(repo) -> BotStatus` (Task 1).
- Produces: `DiagnosisReport` gains `bot_status: BotStatus | None = None` and **loses** `drift_automation_present` / `drift_automation_enabled`; `probe_health` loses its `drift_workflow_path` parameter (and the Actions workflow-list probe at github_platform.py:768-798). Task 3 (scan) consumes the same report shape.

- [ ] **Step 1: Read the current code first.** Read `aviato/core/diagnosis.py`, `cmd_doctor` in `aviato/cli.py` (968-1054), and `probe_health` (`aviato/github_platform.py:608-799`) so the edits below land on real structure. Grep every consumer of the removed fields before editing:

```bash
grep -rn "drift_automation_present\|drift_automation_enabled\|drift_workflow_path\|DRIFT_CALLER_PATH" aviato tests
```

Every hit must be updated in this task or Task 3 (fleet/scan); none may survive to Task 7's gate.

- [ ] **Step 2: Write the failing tests.** In `tests/test_cli_doctor.py`, following its existing fixture/monkeypatch style (see `test_doctor_probes_pages_only_for_docs_and_serve_pages` at line 23 for the pattern), add:

```python
@pytest.mark.parametrize(
    ("bot_status", "expected_fragment"),
    [
        (BotStatus(configured=False, covered=None, last_checked=None, error=None), "bot status: unconfigured"),
        (BotStatus(configured=True, covered=True, last_checked="2026-07-22T06:17:00+00:00", error=None), "bot status: covered"),
        (BotStatus(configured=True, covered=False, last_checked=None, error=None), "not covered by bot automation"),
        (BotStatus(configured=True, covered=None, last_checked=None, error="bot status probe failed: HTTP 401"), "bot status probe failed"),
    ],
)
def test_doctor_reports_bot_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bot_status: BotStatus, expected_fragment: str, tmp_path
) -> None:
    ...  # build the doctor invocation exactly as the neighboring tests do (onboarded tmp repo +
    ...  # monkeypatched platform), additionally monkeypatching aviato.cli.probe_bot_status
    ...  # to return `bot_status`, then assert `expected_fragment` in capsys.readouterr().out
```

Replace the `...` lines with the concrete setup copied from the nearest existing doctor test in that file — the assertion contract above (four fragments, one per BotStatus shape) is the deliverable.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest -q tests/test_cli_doctor.py -k bot_status`
Expected: FAIL — `BotStatus` import error or missing output fragments.

- [ ] **Step 4: Implement.**

1. `aviato/core/diagnosis.py`: in `DiagnosisReport`, delete `drift_automation_present: bool` and `drift_automation_enabled: bool | None`; add:

```python
    bot_status: "BotStatus | None" = None  # drift heartbeat now comes from aviato-bot
```

with `from aviato.botstatus import BotStatus` (or a TYPE_CHECKING import if core must stay platform-agnostic — match the module's existing import discipline; if core avoids non-core imports, define the field as a plain object and keep typing loose, mirroring how the module handles other platform data).

2. `aviato/github_platform.py`: remove the `drift_workflow_path` parameter from `probe_health` and delete the Actions workflow-list probe block (lines 768-798). Keep `scan_heartbeat_present` (security-baseline heartbeat — unrelated) and the issue-channel probe.

3. `aviato/cli.py` `cmd_doctor`: drop `drift_workflow_path=DRIFT_CALLER_PATH` from the `probe_health` call (line 1026); delete the now-unused `DRIFT_CALLER_PATH` constant if nothing else uses it; call `probe_bot_status(repo_slug)` (import from `aviato.botstatus`) and print, following the existing `_tri()` reporter style around lines 1032-1054:
   - unconfigured → `bot status: unconfigured (set AVIATO_BOT_URL and AVIATO_BOT_STATUS_TOKEN)`
   - covered → `bot status: covered (last drift check {last_checked})` (omit the parenthetical when `last_checked` is None)
   - covered is False → `bot status: not covered by bot automation`
   - error → `bot status probe failed: {error}` (print the `error` field verbatim; it already carries the prefix)

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest -q tests/test_cli_doctor.py`
Expected: all pass (update any existing doctor tests that asserted the removed drift-workflow probe output).

- [ ] **Step 6: Commit**

```bash
git add aviato/core/diagnosis.py aviato/github_platform.py aviato/cli.py tests/test_cli_doctor.py
git commit -m "feat!: doctor probes bot repo-status instead of the drift workflow"
```

---

### Task 3: Repoint scan (fleet) at the bot probe

**Files:**
- Modify: `aviato/core/fleet.py`, `aviato/cli.py` (`cmd_scan`, ~1178-1366)
- Test: `tests/test_cli_scan.py`

**Interfaces:**
- Consumes: the Task 2 `DiagnosisReport.bot_status` field and `probe_bot_status`.
- Produces: scan's TSV/report columns replace the drift-automation column with a `bot` column whose values are `unconfigured` / `covered` / `uncovered` / `error`.

- [ ] **Step 1: Read `aviato/core/fleet.py` and `cmd_scan`**, then locate every remaining hit from the Task 2 grep (`drift_automation_*`) in fleet/scan code and tests.

- [ ] **Step 2: Write the failing test.** In `tests/test_cli_scan.py`, following its existing fleet-fixture style, add one parameterized test asserting the scan output row contains the new `bot` column value for a covered and an uncovered repo (monkeypatch `probe_bot_status` as in Task 2; two parametrize cases, `covered` and `uncovered`).

- [ ] **Step 3: Run to verify it fails**

Run: `pytest -q tests/test_cli_scan.py -k bot`
Expected: FAIL.

- [ ] **Step 4: Implement** — thread `bot_status` through fleet diagnosis the same way Task 2 did for doctor (one `probe_bot_status(repo)` call per scanned repo; map to the four column values above), and update the scan reporter/columns.

- [ ] **Step 5: Run to verify pass, then run the whole suite**

Run: `pytest -q tests/test_cli_scan.py` then `pytest -q > /tmp/pytest.log 2>&1; tail -5 /tmp/pytest.log`
Expected: scan tests pass; note remaining failures (they should only concern drift-report/workflows, removed next).

- [ ] **Step 6: Commit**

```bash
git add aviato/core/fleet.py aviato/cli.py tests/test_cli_scan.py
git commit -m "feat!: scan reports bot coverage instead of drift-workflow health"
```

---

### Task 4: Remove the `drift-report` command

**Files:**
- Modify: `aviato/cli.py` (delete `cmd_drift_report` 1907-2075 and its subparser registration at 2476)
- Delete: `tests/test_cli_drift_report.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `aviato drift-report` no longer exists; `aviato.core.drift` remains exported and untouched.

- [ ] **Step 1: Verify remaining callers before deleting**

```bash
grep -rn "run_file_drift\|run_settings_drift\|drift_report\|drift-report" aviato tests --include="*.py" | grep -v core/
```

`cmd_drift_report` must be the only CLI caller of `run_file_drift`/`run_settings_drift`. If another command (e.g. `sync` near `aviato/cli.py:1056`) calls either, that call **stays** — delete only the drift-report command path.

- [ ] **Step 2: Delete** `cmd_drift_report`, its subparser block, its imports that nothing else uses, and `tests/test_cli_drift_report.py`:

```bash
git rm tests/test_cli_drift_report.py
```

- [ ] **Step 3: Write the failing-then-passing guard test.** In the CLI arg-parsing test file (find it: `grep -rln "unrecognized\|invalid choice" tests/`; else add to `tests/test_cli_doctor.py`):

```python
def test_drift_report_command_is_gone(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        aviato.cli.main(["drift-report", "."])
    assert "invalid choice" in capsys.readouterr().err
```

(Adapt the entrypoint call to the module's real `main` signature.)

- [ ] **Step 4: Run the suite**

Run: `pytest -q > /tmp/pytest.log 2>&1; tail -5 /tmp/pytest.log`
Expected: guard test passes; remaining failures only reference the workflows/scaffold (Task 5).

- [ ] **Step 5: Commit**

```bash
git add -A aviato tests
git commit -m "feat!: remove drift-report command (drift detection moved to aviato-bot)"
```

---

### Task 5: Remove workflows, scaffold artifact, and validation expectations

**Files:**
- Delete: `.github/workflows/reusable-consumer-automation.yml`, `.github/workflows/aviato-drift.yml`, `templates/consumer-automation.yml`, `aviato/library/scaffold/wf-drift.yaml`, the scaffold source `files/wf-drift.yml` (locate: `grep -rn "wf-drift" aviato/library`)
- Modify: `aviato/validation.py` (lines 50, 53, 349, 469, 721), all six scaffold bundles (`aviato/library/bundles/scaffold/*-sc.yaml` — remove the `- wf-drift` entry), `tests/test_workflow_guards.py`
- Test: existing validation/scaffold suites

**Interfaces:**
- Consumes: nothing new.
- Produces: consumers drop `.github/workflows/aviato-drift.yml` on their next `sync`/`repin`; `aviato validate` passes with the files gone.

- [ ] **Step 1: Delete the files**

```bash
git rm .github/workflows/reusable-consumer-automation.yml .github/workflows/aviato-drift.yml templates/consumer-automation.yml aviato/library/scaffold/wf-drift.yaml
grep -rn "wf-drift\|consumer-automation" aviato templates .github tests
```

Remove every remaining reference the grep surfaces: the six `- wf-drift` bundle entries, `validation.py` `REQUIRED_FILES` entries (lines 50, 53), the `_INSTALL_URL_COPY_COUNTS` entry (line 349), the cron-parity exclusion (line 469), the template/scaffold-parity check for `templates/consumer-automation.yml` (line 721), and any `tests/test_workflow_guards.py` assertions about drift automation presence.

- [ ] **Step 2: Run validation + the scaffold/sync suites**

Run: `pytest -q tests/test_workflow_guards.py tests/core/test_scaffold.py tests/test_cli_sync.py` and the repo's `validate` command (see README).
Expected: green — sync now treats a consumer's existing `aviato-drift.yml` caller as a managed file to remove (verify: onboarding/sync tests that enumerate managed artifacts no longer include it; if sync does not delete departed managed artifacts, check how earlier artifact removals were handled — `grep -rn "removed\|departed" aviato/core/scaffold.py` — and follow that mechanism).

- [ ] **Step 3: Full suite**

Run: `pytest -q > /tmp/pytest.log 2>&1; tail -5 /tmp/pytest.log`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat!: retire scheduled consumer drift automation workflows"
```

---

### Task 6: Docs, cross-repo contract, and version bump

**Files:**
- Modify: `README.md`, any docs pages mentioning drift-report/consumer automation (`grep -rln "drift-report\|consumer-automation" README.md docs`), `pyproject.toml` (version)
- Modify (sibling repo): `../aviato-bot/README.md`

- [ ] **Step 1: Update aviato docs.** Remove drift-report/consumer-automation sections; document the two probe env vars (`AVIATO_BOT_URL`, `AVIATO_BOT_STATUS_TOKEN`) in doctor/scan docs.

- [ ] **Step 2: Update the bot README's scope contract.** In `../aviato-bot/README.md`, the out-of-scope list still names `drift-report` as a permanent local tool and references the scheduled consumer drift caller (shadow/cutover checklist). Update: drift detection is now bot-owned (webhooks + sweep); `drift-report` no longer exists. Commit that change in the aviato-bot repo:

```bash
git -C ../aviato-bot add README.md
git -C ../aviato-bot commit -m "docs: drift automation is bot-owned; drift-report retired"
```

- [ ] **Step 3: Bump version** in `pyproject.toml`: `0.6.1` → `0.7.0`. Confirm with the repo's own tool: `python -m aviato.cli next-version` style check if applicable (see `cmd_next_version`); otherwise set it directly.

- [ ] **Step 4: Full gate**

```bash
pytest -q > /tmp/pytest.log 2>&1; tail -5 /tmp/pytest.log
./validate.sh > /tmp/validate.log 2>&1; tail -20 /tmp/validate.log
```
Expected: suite green, validate clean. Report exact counts.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: bump to 0.7.0 and document bot-owned drift automation"
```

---

## Verification (whole plan)

- `pytest -q` green in aviato (exact count), `./validate.sh` clean.
- `grep -rn "drift-report\|consumer-automation\|wf-drift\|AVIATO_SETTINGS_TOKEN\b" aviato templates .github docs README.md` returns nothing except intentional history/changelog mentions. (`AVIATO_SETTINGS_READ_TOKEN` and `settings_read_token_scope` remain — doctor/scan still use them.)
- Fresh-context verifier pass over the diff (claim: "legacy scheduled drift automation and drift-report removed; doctor/scan probe the bot endpoint; core drift engine untouched").
