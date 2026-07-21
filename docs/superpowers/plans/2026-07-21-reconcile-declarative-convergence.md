# Reconcile Declarative Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace issue-label consent with declaration-driven reconciliation, make `aviato reconcile .` interactive by default, add explicit noninteractive `--preview` and `--apply` modes, and close drift issues only after a later scan verifies settings and rulesets are clean.

**Architecture:** Split reconciliation into a pure plan builder and a guarded executor. The CLI obtains the declaration, builds and displays a plan, then either previews it, prompts on a TTY, or applies it explicitly. The executor rereads live settings immediately before writing and aborts when the internal diff identity changes. Drift scanning—not reconcile—owns GitHub issue creation and closure.

**Tech Stack:** Python 3.11+, `argparse`, frozen dataclasses, the existing `Platform` protocol, GitHub CLI REST calls, `pytest`, Ruff, Black, mypy strict mode, and Aviato's documentation/traceability checks.

**Global Constraints:**

- Preserve GitHub as the authorization boundary; do not introduce a replacement consent token, issue acknowledgement, or clean-worktree/default-branch gate.
- Keep the diff ID internal. It binds displayed state to apply-time state but is never entered by an operator.
- `--preview` is read-only and exits zero for both clean and drifted declarations.
- `--apply` expresses noninteractive intent but still uses version, representability, and apply-time race guards.
- Default interactive mode must refuse when stdin is not a TTY.
- A partially supported apply is degraded and exits nonzero.
- Drift issues are alert lifecycle records. Reconcile never reads or comments on them.
- Close every matching open drift issue only after both settings and rulesets are verifiably clean; failure to close is an operational failure.
- Legacy `aviato-consent:` labels have no authority. Remove them best-effort when an issue is updated or closed.
- Do not modify issue #116's managed `.gitignore` behavior or the external-watch behavior in issues #119, #120, and #123.

---

## Task 1: Introduce the Pure Plan and Guarded Executor

**Files:**

- Modify: `aviato/core/reconcile.py:1-102`
- Modify: `aviato/core/reconcile_flow.py:1-101`
- Modify: `tests/core/test_reconcile.py:1-173`
- Modify: `tests/core/test_reconcile_flow.py:1-449`

- [ ] **Step 1: Add failing pure-plan tests**

Add tests that pin the plan fields and clean-state behavior while leaving the existing consent tests in place temporarily:

```python
from aviato.core.reconcile import build_reconcile_plan


def test_build_reconcile_plan_captures_the_displayed_snapshot() -> None:
    desired = {"default_branch": "main", "delete_branch_on_merge": True}
    live = {"default_branch": "trunk", "delete_branch_on_merge": False}

    plan = build_reconcile_plan(
        desired_settings=desired,
        live_settings=live,
        pin="0.3.0",
        tool_version="0.3.0",
        recorded_version="0.3.0",
    )

    assert plan.desired_settings == desired
    assert plan.live_settings == live
    assert plan.changes == {
        "default_branch": "destructive",
        "delete_branch_on_merge": "additive",
    }
    assert plan.values == {
        "default_branch": {"desired": "main", "live": "trunk"},
        "delete_branch_on_merge": {"desired": True, "live": False},
    }
    assert len(plan.diff_id) == 32
    assert plan.pin == "0.3.0"
    assert plan.tool_version == "0.3.0"
    assert plan.recorded_version == "0.3.0"
    assert plan.clean is False


def test_build_reconcile_plan_marks_equal_settings_clean() -> None:
    settings = {"default_branch": "main", "delete_branch_on_merge": True}

    plan = build_reconcile_plan(
        desired_settings=settings,
        live_settings=settings,
        pin="0.3.0",
        tool_version="0.3.0",
        recorded_version="0.3.0",
    )

    assert plan.clean is True
    assert plan.changes == {}
    assert plan.values == {}
```

- [ ] **Step 2: Run the pure-plan tests and confirm they fail**

Run:

```bash
python -m pytest tests/core/test_reconcile.py -q
```

Expected: failure because `build_reconcile_plan` and `ReconcilePlan` do not exist.

- [ ] **Step 3: Add failing executor tests**

Extend `tests/core/test_reconcile_flow.py` with tests for a clean no-op, a changed live snapshot, a successful apply, and a degraded apply. Use `FakePlatform.settings` to change state between planning and execution:

```python
from aviato.core.reconcile_flow import execute_reconcile, plan_reconcile


def test_execute_reconcile_aborts_when_live_diff_changes() -> None:
    platform = FakePlatform(
        settings={"default_branch": "trunk", "delete_branch_on_merge": False}
    )
    desired = {"default_branch": "main", "delete_branch_on_merge": True}
    plan = plan_reconcile(
        platform,
        repo="owner/repo",
        desired_settings=desired,
        pin="0.3.0",
        tool_version="0.3.0",
        recorded_version="0.3.0",
    )
    platform.settings = {
        "default_branch": "release",
        "delete_branch_on_merge": False,
    }

    outcome = execute_reconcile(
        platform,
        repo="owner/repo",
        plan=plan,
    )

    assert outcome.action == "abort"
    assert "apply_settings" not in platform.call_names()


def test_execute_reconcile_applies_the_current_declaration() -> None:
    platform = FakePlatform(settings={"default_branch": "trunk"})
    desired = {"default_branch": "main"}
    plan = plan_reconcile(
        platform,
        repo="owner/repo",
        desired_settings=desired,
        pin="0.3.0",
        tool_version="0.3.0",
        recorded_version="0.3.0",
    )

    outcome = execute_reconcile(
        platform,
        repo="owner/repo",
        plan=plan,
    )

    assert outcome.action == "apply"
    assert next(args for name, args in platform.calls if name == "apply_settings") == (
        "owner/repo",
        desired,
        {"default_branch": "trunk"},
    )


def test_execute_reconcile_reports_skipped_fields_as_degraded() -> None:
    platform = FakePlatform(settings={"default_branch": "trunk"})
    platform.skipped_on_apply = ["rulesets"]
    platform.notes_on_apply = ["rulesets require a supported API shape"]
    plan = plan_reconcile(
        platform,
        repo="owner/repo",
        desired_settings={"default_branch": "main"},
        pin="0.3.0",
        tool_version="0.3.0",
        recorded_version="0.3.0",
    )

    outcome = execute_reconcile(
        platform,
        repo="owner/repo",
        plan=plan,
    )

    assert outcome.action == "degraded"
    assert outcome.skipped == ("rulesets",)
    assert outcome.notes == ("rulesets require a supported API shape",)
```

Also retain focused cases for incompatible versions, the explicit version-pin override, and a clean plan that does not call `apply_settings`.

- [ ] **Step 4: Run the executor tests and confirm they fail**

Run:

```bash
python -m pytest tests/core/test_reconcile_flow.py -q
```

Expected: import failures for `plan_reconcile` and `execute_reconcile`.

- [ ] **Step 5: Implement `ReconcilePlan` and the new outcome model**

Add the following declaration-driven types and builder to `aviato/core/reconcile.py`. Retain the old consent state machine until Task 2 so unrelated tests stay green during this commit.

```python
from dataclasses import dataclass
from typing import Any, Literal

from .settingsdrift import classify_settings, diff_identity

ReconcileAction = Literal["apply", "noop", "abort", "refuse", "degraded"]


@dataclass(frozen=True)
class ReconcilePlan:
    desired_settings: dict[str, Any]
    live_settings: dict[str, Any]
    diff_id: str
    changes: dict[str, str]
    values: dict[str, dict[str, Any]]
    pin: str
    tool_version: str
    recorded_version: str

    @property
    def clean(self) -> bool:
        return not self.changes


@dataclass(frozen=True)
class DeclarativeReconcileOutcome:
    action: ReconcileAction
    reason: str
    skipped: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def build_reconcile_plan(
    *,
    desired_settings: dict[str, Any],
    live_settings: dict[str, Any],
    pin: str,
    tool_version: str,
    recorded_version: str,
) -> ReconcilePlan:
    diff = classify_settings(desired=desired_settings, live=live_settings)
    return ReconcilePlan(
        desired_settings=dict(desired_settings),
        live_settings=dict(live_settings),
        diff_id=diff_identity(diff),
        changes=dict(diff.changes),
        values={key: dict(value) for key, value in diff.values.items()},
        pin=pin,
        tool_version=tool_version,
        recorded_version=recorded_version,
    )
```

- [ ] **Step 6: Implement planning and guarded execution**

Add these functions to `aviato/core/reconcile_flow.py` next to the old `run_reconcile` entry point:

```python
from typing import Any

from .errors import CompatibilityError
from .reconcile import (
    DeclarativeReconcileOutcome,
    ReconcilePlan,
    build_reconcile_plan,
)
from .version import is_compatible


def plan_reconcile(
    platform: Platform,
    *,
    repo: str,
    desired_settings: dict[str, Any],
    pin: str,
    tool_version: str,
    recorded_version: str,
) -> ReconcilePlan:
    return build_reconcile_plan(
        desired_settings=desired_settings,
        live_settings=platform.read_settings(repo),
        pin=pin,
        tool_version=tool_version,
        recorded_version=recorded_version,
    )


def execute_reconcile(
    platform: Platform,
    *,
    repo: str,
    plan: ReconcilePlan,
    override_version_pin: bool = False,
) -> DeclarativeReconcileOutcome:
    if plan.clean:
        return DeclarativeReconcileOutcome("noop", "settings already match")

    try:
        compatible = is_compatible(
            tool=plan.tool_version,
            pinned=plan.pin,
            recorded=plan.recorded_version,
        )
    except CompatibilityError:
        compatible = False

    if not compatible and not override_version_pin:
        return DeclarativeReconcileOutcome(
            "refuse",
            "tool version does not satisfy the recorded compatibility contract",
        )

    final_live = platform.read_settings(repo)
    final_plan = build_reconcile_plan(
        desired_settings=plan.desired_settings,
        live_settings=final_live,
        pin=plan.pin,
        tool_version=plan.tool_version,
        recorded_version=plan.recorded_version,
    )
    if final_plan.diff_id != plan.diff_id:
        return DeclarativeReconcileOutcome(
            "abort",
            "live settings changed after the plan was displayed; rerun reconcile",
        )

    result = platform.apply_settings(
        repo,
        plan.desired_settings,
        expected_live=final_live,
    )
    if result.skipped:
        return DeclarativeReconcileOutcome(
            "degraded",
            "supported settings were applied but some fields were skipped",
            skipped=result.skipped,
            notes=result.notes,
        )
    return DeclarativeReconcileOutcome(
        "apply",
        "current declaration applied",
        notes=result.notes,
    )
```

- [ ] **Step 7: Run focused core tests**

Run:

```bash
python -m pytest tests/core/test_reconcile.py tests/core/test_reconcile_flow.py -q
```

Expected: all old and new tests pass.

- [ ] **Step 8: Commit the planner/executor slice**

```bash
git add aviato/core/reconcile.py aviato/core/reconcile_flow.py tests/core/test_reconcile.py tests/core/test_reconcile_flow.py
git commit -m "feat: add declaration-driven reconcile planner"
```

---

## Task 2: Replace the CLI Consent Ceremony with Three Execution Modes

**Files:**

- Modify: `aviato/cli.py:2197-2277`
- Modify: `aviato/cli.py:2527-2542`
- Modify: `aviato/core/reconcile.py:1-102`
- Modify: `aviato/core/reconcile_flow.py:1-140`
- Rewrite: `tests/test_cli_reconcile.py:1-368`
- Rewrite: `tests/core/test_reconcile.py:1-220`
- Rewrite: `tests/core/test_reconcile_flow.py:1-520`

- [ ] **Step 1: Write failing parser and mode tests**

Cover these contracts in `tests/test_cli_reconcile.py`:

```python
class _Stdin:
    def __init__(self, *, interactive: bool) -> None:
        self.interactive = interactive

    def isatty(self) -> bool:
        return self.interactive


def test_reconcile_preview_is_read_only_and_returns_zero_for_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _consumer(tmp_path)
    platform = _FakePlatform(settings={"default_branch": "trunk"})
    _wire(monkeypatch, platform)

    result = cli.main(["reconcile", str(root), "--preview"])

    assert result == 0
    assert platform.applied == []


def test_reconcile_apply_is_noninteractive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _consumer(tmp_path)
    platform = _FakePlatform(settings={"default_branch": "trunk"})
    _wire(monkeypatch, platform)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail(prompt))

    result = cli.main(["reconcile", str(root), "--apply"])

    assert result == 0
    assert len(platform.applied) == 1


def test_reconcile_default_prompts_on_a_tty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _consumer(tmp_path)
    platform = _FakePlatform(settings={"default_branch": "trunk"})
    _wire(monkeypatch, platform)
    monkeypatch.setattr(cli.sys, "stdin", _Stdin(interactive=True))
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")

    result = cli.main(["reconcile", str(root)])

    assert result == 0
    assert len(platform.applied) == 1


def test_reconcile_default_refuses_without_a_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", _Stdin(interactive=False))

    result = cli.main(["reconcile", "."])

    assert result == 2


def test_reconcile_preview_and_apply_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["reconcile", ".", "--preview", "--apply"])

    assert exc_info.value.code == 2


def test_reconcile_rejects_the_removed_issue_and_confirm_syntax() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["reconcile", ".", "settings-drift", "--confirm", "abc"])

    assert exc_info.value.code == 2
```

Add cases for prompt rejection, EOF at the prompt, a clean plan that never prompts, apply-time drift, incompatible versions with and without override, `--preview --override-version-pin` rejection, and degraded apply returning nonzero while printing every skipped field and note.

Change `_FakePlatform.__init__` to accept `issue: Issue | None = None` during this transitional task, and keep recording applied payloads in `self.applied`. The obsolete issue methods remain only to satisfy the pre-Task-3 protocol and must not appear in reconcile call assertions.

- [ ] **Step 2: Run the CLI tests and confirm they fail**

Run:

```bash
python -m pytest tests/test_cli_reconcile.py -q
```

Expected: parser and behavior failures because issue and `--confirm` are still required.

- [ ] **Step 3: Replace the reconcile parser**

Replace the reconcile parser block in `aviato/cli.py` with:

```python
reconcile = subparsers.add_parser(
    "reconcile",
    help="Converge live repository settings to the current declaration.",
)
reconcile.add_argument("path", nargs="?", default=".")
reconcile_mode = reconcile.add_mutually_exclusive_group()
reconcile_mode.add_argument(
    "--preview",
    action="store_true",
    help="Display the current plan without applying it.",
)
reconcile_mode.add_argument(
    "--apply",
    action="store_true",
    help="Apply the current plan without an interactive prompt.",
)
reconcile.add_argument("--recorded-version")
reconcile.add_argument("--override-version-pin", action="store_true")
reconcile.set_defaults(func=cmd_reconcile)
```

- [ ] **Step 4: Replace `cmd_reconcile`**

Refactor `cmd_reconcile` to this control flow, preserving the existing input validation and most-restrictive recorded-version calculation:

```python
def cmd_reconcile(args: argparse.Namespace) -> int:
    if not args.preview and not args.apply and not sys.stdin.isatty():
        print(
            "error: interactive reconcile requires a TTY; use --preview or --apply",
            file=sys.stderr,
        )
        return 2
    if args.preview and args.override_version_pin:
        print(
            "error: --override-version-pin is only valid when applying",
            file=sys.stderr,
        )
        return 2

    root = Path(args.path).resolve()
    declaration_path = _consumer_declaration_target(
        root,
        operation="inspect declaration",
    )
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}", file=sys.stderr)
        return 2

    repo = normalize_slug(remote_url(root))
    if not repo:
        print(
            "could not determine OWNER/REPO from the repository remote",
            file=sys.stderr,
        )
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = _load_consumer_declaration(root)
        resolved = resolve_profile(
            registry,
            declaration.profile,
            overrides=declaration.overrides,
            docs=declaration.docs,
        )
        expected = _expected_artifacts(registry, declaration)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    recorded_markers = _recorded_versions(root, expected)
    recorded_version = (
        args.recorded_version
        or (
            most_restrictive_recorded(recorded_markers)
            if recorded_markers
            else None
        )
        or declaration.version
    )
    desired_settings = _desired_settings(resolved)
    platform = GitHubPlatform()
    try:
        plan = plan_reconcile(
            platform,
            repo=repo,
            desired_settings=desired_settings,
            pin=declaration.version,
            tool_version=__version__,
            recorded_version=recorded_version,
        )
    except GitHubAPIError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1
    _print_reconcile_plan(plan)

    if args.preview or plan.clean:
        return 0

    if not args.apply:
        try:
            answer = input("Apply these settings? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            print("Reconcile cancelled; no settings were changed.")
            return 0

    try:
        outcome = execute_reconcile(
            platform,
            repo=repo,
            plan=plan,
            override_version_pin=args.override_version_pin,
        )
    except GitHubAPIError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1
    except UnmodeledProtectionError as exc:
        print(f"reconcile aborted (fail-closed): {exc}", file=sys.stderr)
        return 1
    except CommandError as exc:
        print(
            "reconcile failed during apply "
            f"(a change may have partially landed): {exc}",
            file=sys.stderr,
        )
        return 1
    print(outcome.reason)
    for skipped in outcome.skipped:
        print(f"skipped: {skipped}", file=sys.stderr)
    for note in outcome.notes:
        print(f"note: {note}", file=sys.stderr)
    return 0 if outcome.action in {"apply", "noop"} else 1
```

Add the deterministic renderer next to `cmd_reconcile`:

```python
def _print_reconcile_plan(plan: ReconcilePlan) -> None:
    if plan.clean:
        print("No settings drift: live state already matches desired.")
        return
    print("Settings reconcile plan:")
    for key, kind in sorted(plan.changes.items()):
        values = plan.values.get(key, {})
        print(
            f"  {key}: {kind} "
            f"({values.get('live')!r} -> {values.get('desired')!r})"
        )
```

Do not print `plan.diff_id`; it is an internal race binding, not an operator challenge.

- [ ] **Step 5: Remove the replaced consent state machine**

Delete `ReconcileState`, the old `ReconcileOutcome`, and `reconcile_decision` from `aviato/core/reconcile.py`. Rename `DeclarativeReconcileOutcome` to `ReconcileOutcome` and update imports. Delete `run_reconcile` from `aviato/core/reconcile_flow.py`, including issue lookup, consent lookup, issue comments, and second consent reads.

Rewrite `tests/core/test_reconcile.py` and `tests/core/test_reconcile_flow.py` so they cover only the pure plan and guarded executor. Preserve tests for:

- exact version compatibility;
- explicit override during apply;
- apply-time reread before any write;
- diff-identity mismatch abort;
- `expected_live` binding;
- unmodeled-protection and representability failures from the platform;
- skipped fields and notes;
- no issue reads or comments.

- [ ] **Step 6: Run the reconcile test slice**

Run:

```bash
python -m pytest tests/core/test_reconcile.py tests/core/test_reconcile_flow.py tests/test_cli_reconcile.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Run static checks on changed Python files**

Run:

```bash
python -m ruff check aviato/cli.py aviato/core/reconcile.py aviato/core/reconcile_flow.py tests/test_cli_reconcile.py tests/core/test_reconcile.py tests/core/test_reconcile_flow.py
python -m mypy --strict aviato tests
```

Expected: both commands pass.

- [ ] **Step 8: Commit the CLI cutover**

```bash
git add aviato/cli.py aviato/core/reconcile.py aviato/core/reconcile_flow.py tests/test_cli_reconcile.py tests/core/test_reconcile.py tests/core/test_reconcile_flow.py
git commit -m "feat: make reconcile declaration driven"
```

---

## Task 3: Make Drift Scanning Close Verified-Clean Issues

**Files:**

- Modify: `aviato/core/ports.py:1-78`
- Modify: `aviato/core/settings_drift_flow.py:1-145`
- Modify: `aviato/github_platform.py:819-871`
- Modify: `tests/core/fakeplatform.py:1-91`
- Modify: `tests/core/test_settings_drift_flow.py:1-205`
- Modify: `tests/test_github_platform.py`
- Modify: `tests/test_cli_drift_report.py:1-310`
- Modify: `tests/test_cli_provision.py:1-57`

- [ ] **Step 1: Write failing core lifecycle tests**

Replace consent-revocation assertions in `tests/core/test_settings_drift_flow.py` with issue-closure assertions:

```python
def test_clean_scan_closes_matching_open_issues() -> None:
    platform = FakePlatform(settings=DESIRED_SETTINGS)
    platform.open_issue_counts["settings-drift"] = 2

    outcome = run_settings_drift(
        platform,
        repo="owner/repo",
        issue_key="settings-drift",
        desired_settings=DESIRED_SETTINGS,
        drifted_rulesets=(),
    )

    assert outcome.status == "resolved"
    assert outcome.closed_issues == 2
    assert next(args for name, args in platform.calls if name == "close_issues") == (
        "owner/repo",
        "settings-drift",
    )
    assert "comment_issue" not in platform.call_names()


def test_clean_scan_without_open_issue_is_clean() -> None:
    platform = FakePlatform(settings=DESIRED_SETTINGS)

    outcome = run_settings_drift(
        platform,
        repo="owner/repo",
        issue_key="settings-drift",
        desired_settings=DESIRED_SETTINGS,
        drifted_rulesets=(),
    )

    assert outcome.status == "clean"
    assert outcome.closed_issues == 0


def test_drift_issue_body_uses_the_three_supported_reconcile_modes() -> None:
    platform = FakePlatform(settings={"default_branch": "trunk"})

    run_settings_drift(
        platform,
        repo="owner/repo",
        issue_key="settings-drift",
        desired_settings=DESIRED_SETTINGS,
        drifted_rulesets=(),
    )

    _, args = next(
        call for call in platform.calls if call[0] == "open_or_update_issue"
    )
    body = args[3]
    assert isinstance(body, str)
    assert "aviato reconcile ." in body
    assert "aviato reconcile . --preview" in body
    assert "aviato reconcile . --apply" in body
    assert "--confirm" not in body
    assert "Diff id:" not in body
```

Retain the test that settings must be clean and `drifted_rulesets` must be empty before closure.

- [ ] **Step 2: Write failing GitHub binding tests**

Add tests that prove `GitHubPlatform.close_issues`:

- fetches every open issue matching the key;
- closes every match with `state=closed` and `state_reason=completed`;
- returns the number closed;
- treats a failed close as an error;
- removes all labels beginning `aviato-consent:` before update or closure;
- logs a warning and continues when legacy-label deletion fails; and
- creates a new issue on later drift because the update lookup considers open issues only.

Use the existing GitHub command fakes and assert the close request payload exactly:

```python
assert close_payloads == [
    {"state": "closed", "state_reason": "completed"},
    {"state": "closed", "state_reason": "completed"},
]
```

- [ ] **Step 3: Run the lifecycle tests and confirm they fail**

Run:

```bash
python -m pytest tests/core/test_settings_drift_flow.py tests/test_github_platform.py tests/test_cli_drift_report.py -q
```

Expected: failures because the protocol cannot close issues and clean scans still comment/revoke consent.

- [ ] **Step 4: Add the protocol operation and outcome evidence**

Add this operation to `Platform` in `aviato/core/ports.py`:

```python
def close_issues(self, repo: str, key: str) -> int:
    """Close every open issue carrying the Aviato issue key; return the count."""
    ...
```

Update every protocol fake in `tests/core/fakeplatform.py`, `tests/test_cli_reconcile.py`, `tests/test_cli_drift_report.py`, and `tests/test_cli_provision.py`.

In the shared `FakePlatform`, initialize `open_issue_counts` from the existing single-issue fixture and allow tests to override it for duplicate coverage:

```python
self.open_issue_counts = {
    key: 1 for key, issue in self.issues.items() if issue.open
}


def close_issues(self, repo: str, key: str) -> int:
    if self.issues_disabled:
        raise RuntimeError("issue channel unavailable")
    self.calls.append(("close_issues", (repo, key)))
    count = self.open_issue_counts.get(key, 0)
    self.open_issue_counts[key] = 0
    issue = self.issues.get(key)
    if issue is not None:
        self.issues[key] = dataclasses.replace(issue, open=False)
    return count
```

Change `SettingsDriftOutcome` to record closure evidence:

```python
Status = Literal["clean", "resolved", "reported"]


@dataclass(frozen=True)
class SettingsDriftOutcome:
    status: Status
    destructive: bool = False
    drifted_rulesets: tuple[str, ...] = ()
    closed_issues: int = 0
```

In the clean branch of `run_settings_drift`, call `platform.close_issues(repo, key)` and return `resolved` only when the count is positive. Remove clean-scan comments, stale-consent revocation, the drift outcome's diff ID, and the `diff_identity` re-export from this module. Rewrite the drift issue body to omit `Diff id:` and document the interactive, preview, and apply forms without an issue key or confirmation ID. Import `diff_identity` directly from `settingsdrift` only in reconcile planning and its focused tests.

- [ ] **Step 5: Implement close-all and legacy-label cleanup in GitHubPlatform**

Keep a narrowly named migration constant in `aviato/github_platform.py`:

```python
LEGACY_CONSENT_LABEL_PREFIX = "aviato-consent:"


def _legacy_consent_labels(issue: dict[str, Any]) -> tuple[str, ...]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return ()
    names: list[str] = []
    for label in labels:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.startswith(LEGACY_CONSENT_LABEL_PREFIX):
            names.append(name)
    return tuple(names)
```

Add a private helper that deletes every matching legacy label using the existing URL quoting and GitHub command wrappers:

```python
@staticmethod
def _remove_legacy_consent_labels(repo: str, issue: dict[str, Any]) -> None:
    number = issue.get("number")
    if not isinstance(number, int):
        return
    for label in _legacy_consent_labels(issue):
        endpoint = f"repos/{repo}/issues/{number}/labels/{_seg(label)}"
        result = github.run(
            ["gh", "api", "--method", "DELETE", endpoint],
            check=False,
        )
        if result.returncode != 0 and "http 404" not in result.stderr.lower():
            print(
                f"WARNING: could not remove legacy label {label!r} "
                f"from {repo}#{number}: {result.stderr.strip()}",
                file=sys.stderr,
            )
```

The helper ignores a 404, emits a warning for other failures, and never confers authority.

Implement the public operation with the same paginated issue listing/key matching used by `open_or_update_issue`. Exclude pull requests returned by GitHub's issues endpoint, and fail loudly if a matching issue lacks an integer number:

```python
def close_issues(self, repo: str, key: str) -> int:
    response = github.gh_json_paginated_optional(
        f"repos/{repo}/issues?state=open&labels={_seg(key)}",
        default=[],
    )
    if not isinstance(response, list):
        raise github.GitHubAPIError(
            f"repos/{repo}/issues",
            0,
            "matching issue response is not a list",
        )
    issues: list[dict[str, Any]] = []
    for issue in response:
        if not isinstance(issue, dict):
            raise github.GitHubAPIError(
                f"repos/{repo}/issues",
                0,
                "matching issue response contains a non-object entry",
            )
        if "pull_request" not in issue:
            issues.append(issue)
    closed = 0
    for issue in issues:
        number = issue.get("number")
        if not isinstance(number, int):
            raise github.GitHubAPIError(
                f"repos/{repo}/issues",
                0,
                "matching issue response is missing an integer number",
            )
        self._remove_legacy_consent_labels(repo, issue)
        self._gh_input(
            ["--method", "PATCH", f"repos/{repo}/issues/{number}"],
            {"state": "closed", "state_reason": "completed"},
        )
        closed += 1
    return closed
```

Call `_remove_legacy_consent_labels` from `open_or_update_issue` before updating an existing issue as well. Keep `_select_issue` for update behavior; close deliberately iterates every valid open match.

- [ ] **Step 6: Update CLI reporting tests**

Make the drift-report command print the closed count for a resolved scan and return nonzero if issue listing or closure fails. Do not swallow a partial-close failure. The next scan will safely retry any still-open matches.

- [ ] **Step 7: Run the affected suite**

Run:

```bash
python -m pytest tests/core/test_settings_drift_flow.py tests/test_github_platform.py tests/test_cli_drift_report.py tests/test_cli_provision.py tests/test_cli_reconcile.py -q
python -m mypy --strict aviato tests
```

Expected: all commands pass.

- [ ] **Step 8: Commit verified-clean closure**

```bash
git add aviato/core/ports.py aviato/core/settings_drift_flow.py aviato/github_platform.py tests/core/fakeplatform.py tests/core/test_settings_drift_flow.py tests/test_github_platform.py tests/test_cli_drift_report.py tests/test_cli_provision.py tests/test_cli_reconcile.py
git commit -m "feat: auto-close verified drift issues"
```

---

## Task 4: Remove Runtime Issue-Consent Plumbing

**Files:**

- Modify: `aviato/core/ports.py:1-78`
- Modify: `aviato/github_platform.py:1-180`
- Modify: `aviato/github_platform.py:559-606`
- Modify: `aviato/github_platform.py:801-871`
- Modify: `tests/core/fakeplatform.py:1-100`
- Modify: `tests/test_github_platform.py`
- Modify: `tests/test_cli_reconcile.py`
- Modify: `tests/test_cli_drift_report.py`
- Modify: `tests/test_cli_provision.py`
- Modify: `tests/core/test_ports.py`

- [ ] **Step 1: Add a negative protocol test**

Update `tests/core/test_ports.py` to define the minimal expected platform and assert it satisfies `Platform` without issue reads, issue comments, or consent revocation. Keep `open_or_update_issue` and `close_issues` because drift reporting owns those operations.

- [ ] **Step 2: Run the protocol and platform tests before cleanup**

Run:

```bash
python -m pytest tests/core/test_ports.py tests/test_github_platform.py -q
```

Expected: the new minimal protocol fake fails structural conformance while the obsolete methods remain required.

- [ ] **Step 3: Remove obsolete protocol surface**

Delete the `Issue` dataclass and these methods from `Platform`:

```python
get_issue
comment_issue
revoke_consent
```

Retain only the alert-lifecycle methods:

```python
open_or_update_issue
close_issues
```

- [ ] **Step 4: Remove GitHub consent interpretation**

Delete from `aviato/github_platform.py`:

- actor-role and privileged-role constants used only for consent;
- `ConsentGrant` and timeline ordering helpers;
- label-event and nonhuman-edit-after-grant logic;
- `current_consent` and `_actor_role`;
- `get_issue`, `comment_issue`, and `revoke_consent`.

Retain only `LEGACY_CONSENT_LABEL_PREFIX` and `_remove_legacy_consent_labels` as a migration cleanup. The cleanup helper must not parse a diff ID, actor, role, timestamp, or event ordering.

Rewrite `_select_issue` and the module/protocol docstrings in alert-lifecycle terms. Remove statements that issues are an authorization or apply audit channel, and describe `apply_settings` as the only repository-settings mutation rather than the protocol's only mutation of any kind.

- [ ] **Step 5: Remove obsolete tests and fake methods**

Delete consent/timeline/role/get/comment/revoke cases from `tests/test_github_platform.py`. Remove the three obsolete methods from all structural protocol fakes. Keep close-all and best-effort legacy-label cleanup coverage.

- [ ] **Step 6: Run the platform boundary suite**

Run:

```bash
python -m pytest tests/core/test_ports.py tests/test_github_platform.py tests/test_cli_reconcile.py tests/test_cli_drift_report.py tests/test_cli_provision.py -q
python -m ruff check aviato/core/ports.py aviato/github_platform.py tests
python -m mypy --strict aviato tests
```

Expected: all commands pass and there are no runtime references to removed protocol methods.

- [ ] **Step 7: Commit the boundary cleanup**

```bash
git add aviato/core/ports.py aviato/github_platform.py tests/core/fakeplatform.py tests/core/test_ports.py tests/test_github_platform.py tests/test_cli_reconcile.py tests/test_cli_drift_report.py tests/test_cli_provision.py
git commit -m "refactor: remove issue consent plumbing"
```

---

## Task 5: Retire Consent Vocabulary and Align Normative Documentation

**Files:**

- Delete: `aviato/core/consent.py`
- Delete: `tests/core/test_consent.py`
- Modify: `aviato/core/errors.py:1-31`
- Modify: `aviato/core/settingsdrift.py:1-57`
- Modify: `tests/core/test_errors.py:1-31`
- Modify: `tests/core/test_settingsdrift.py`
- Modify: `tests/core/test_settings_drift_flow.py:160-181`
- Modify: `README.md`
- Modify: `zensical.toml`
- Modify: `docs/guide/getting-started.md`
- Modify: `docs/guide/cli.md`
- Modify: `docs/architecture/infrastructure.md`
- Modify: `docs/specifications/modules/reconcile/flow.md`
- Rename: `docs/specifications/modules/reconcile/consent.md` to `docs/specifications/modules/reconcile/authorization.md`
- Modify: `docs/specifications/modules/drift/settings-drift.md`
- Modify: `docs/specifications/modules/fleet/scan.md`
- Modify: `docs/specifications/core/consumer-contract.md`
- Modify: `docs/requirements/README.md`
- Modify: `docs/requirements/core/principles.md`
- Modify: `docs/requirements/core/state-and-failures.md`
- Modify: `docs/requirements/core/structure.md`
- Modify: `docs/requirements/core/glossary.md`
- Modify: `docs/requirements/traceability.md`
- Modify: `docs/security/controls.md`
- Modify: `docs/security/threat-model.md`
- Modify: `docs/requirements/evidence/2026-07-18-deploy-proofs.md`
- Modify: `tests/test_docs_index.py`

- [ ] **Step 1: Add failing active-document contract tests**

Add a focused test in `tests/test_docs_index.py` that reads the active operator, specification, requirement, and security documents listed above and asserts:

```python
for path in active_reconcile_docs:
    text = path.read_text(encoding="utf-8")
    assert "--confirm" not in text
    assert "aviato reconcile . ISSUE" not in text
    assert "core.consent" not in text

cli_guide = (repo_root / "docs/guide/cli.md").read_text(encoding="utf-8")
assert "aviato reconcile . --preview" in cli_guide
assert "aviato reconcile . --apply" in cli_guide
```

Do not include historical implementation plans or the approved design record in `active_reconcile_docs`; those artifacts intentionally explain the migration.

- [ ] **Step 2: Run the documentation contract test and confirm it fails**

Run:

```bash
python -m pytest tests/test_docs_index.py -q
```

Expected: failures on the old issue/confirm syntax and consent-module references.

- [ ] **Step 3: Remove the dead consent module and rename the internal identity constant**

Delete `aviato/core/consent.py` and `tests/core/test_consent.py`. Remove `AuthorizationError` and its registry assertion because no authorization decision remains in core.

Rename the misleading hash-length constant in `aviato/core/settingsdrift.py`:

```python
DIFF_ID_HEX_LEN = 32


def diff_identity(diff: SettingsDiff) -> str:
    payload = {
        key: {
            "kind": kind,
            "desired": diff.values.get(key, {}).get("desired"),
            "live": diff.values.get(key, {}).get("live"),
        }
        for key, kind in diff.changes.items()
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:DIFF_ID_HEX_LEN]
```

Update the focused tests to assert `DIFF_ID_HEX_LEN` as an internal plan/race-binding invariant, not a GitHub label-size invariant.

- [ ] **Step 4: Rewrite the operator contract**

Update `README.md`, the getting-started guide, the CLI guide, and architecture overview with this exact command model:

```text
aviato reconcile .             # preview, prompt, then apply on an interactive TTY
aviato reconcile . --preview   # preview only; safe for automation
aviato reconcile . --apply     # explicit noninteractive apply
```

Document that `--preview` and `--apply` are mutually exclusive, default mode refuses without a TTY, `--override-version-pin` is apply-only, clean and cancelled interactive runs exit zero, apply-time drift and degraded applies exit nonzero, and an issue is never an input to reconcile.

- [ ] **Step 5: Rewrite the module specifications**

Rename `consent.md` to `authorization.md`. Specify:

- GitHub permissions and branch/ruleset protections are the authorization boundary;
- CLI mode selection expresses operator intent but does not add a second authorization system;
- the plan's diff ID is an internal race binding;
- the executor rereads immediately before applying and compares identities;
- `expected_live` remains the write binding;
- representability, unmodeled-protection, and version guards remain mandatory;
- skipped fields produce degraded failure;
- reconcile does not mutate issues; and
- declaration commits/PRs record intended policy while GitHub's native audit surfaces record actual platform mutations where available.

Update the Zensical navigation entry and the canonical documentation list in `tests/test_docs_index.py` to use `specifications/modules/reconcile/authorization.md`.

Update drift and fleet specifications so the scanner opens/updates issues for drift and closes every matching open issue only after settings and rulesets are both clean. State that recurrence creates a new issue after prior matches were closed.

- [ ] **Step 6: Update requirements and traceability**

Revise requirement rows and their owning sections consistently:

- **2.7:** authorization is enforced by GitHub/platform permissions; interactive/default and explicit apply modes express intent.
- **2.8:** apply uses the current declaration and an apply-time reread/identity check; no issue consent record.
- **5.7:** drift opens or updates its keyed issue and exposes the three reconcile forms.
- **5.8:** verified-clean settings and rulesets close all matching open issues; closure failure is operational failure.
- **SEC-006:** GitHub authorization plus explicit execution mode, race binding, version compatibility, and representability protections replace label consent.

Replace the glossary's consent record with `reconcile plan` and `diff identity`. Update the historical deploy-proof link to the renamed authorization specification without rewriting the historical evidence itself.

- [ ] **Step 7: Update the threat model without understating automation authority**

Replace the assumption that unattended automation may never apply with this boundary:

```text
An authenticated operator or explicitly configured automation may invoke apply
only with GitHub-granted repository permission. Implicit/default non-TTY execution
refuses; automation must select --apply explicitly.
```

Update THREAT-006 so mitigations are concrete: GitHub authentication/authorization, explicit mode selection, version checks, apply-time reread and diff-identity comparison, `expected_live`, representability checks, and degraded failure reporting.

- [ ] **Step 8: Scan for stale active-contract language**

Run:

```bash
rg -n --glob '!docs/superpowers/plans/**' --glob '!docs/superpowers/specs/**' 'core\.consent|CONSENT_ID_HEX_LEN|--confirm|reconcile \. [A-Z_-]*ISSUE' aviato tests README.md docs
```

Expected: no matches. A literal `aviato-consent:` may remain only in the narrowly scoped GitHub migration cleanup and its tests/specification.

- [ ] **Step 9: Run focused documentation and core tests**

Run:

```bash
python -m pytest tests/test_docs_index.py tests/core/test_errors.py tests/core/test_settingsdrift.py tests/core/test_settings_drift_flow.py -q
```

Expected: all tests pass.

- [ ] **Step 10: Run the complete local release gate**

Run:

```bash
./scripts/validate.sh
```

Expected: compilation, Aviato validation, documentation sync, template regeneration checks, Ruff, Black, pytest with coverage, wheel build, mypy strict mode, and all installed shell/YAML/action checks pass.

If every optional validation tool is installed, also run:

```bash
AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh
```

Expected: no missing-tool allowance and a zero exit status.

- [ ] **Step 11: Commit the contract migration**

```bash
git add -A aviato/core tests/core tests/test_docs_index.py README.md zensical.toml docs
git commit -m "docs: align reconcile authorization contract"
```

---

## Task 6: Final Spec-Coverage and Regression Review

**Files:**

- Review: `docs/superpowers/specs/2026-07-21-reconcile-declarative-convergence-design.md`
- Review: all files changed in Tasks 1-5

- [ ] **Step 1: Compare the implementation to every approved design decision**

Build a checklist from the design's CLI, core flow, issue lifecycle, safety, migration, and out-of-scope sections. Confirm each item has both implementation and test evidence. Pay special attention to these easy-to-miss cases:

- clean default mode does not prompt;
- default non-TTY refuses before any GitHub read;
- preview never applies and does not need version override;
- apply-time changed drift aborts before `apply_settings`;
- degraded apply exits nonzero and preserves notes;
- close-all handles multiple matching issues;
- legacy label cleanup failure never blocks closure;
- reconcile has no issue side effects;
- no behavior from issue #116 entered this change.

- [ ] **Step 2: Inspect the final diff for accidental scope and placeholders**

Run:

```bash
git diff --check EXECUTION_BASE..HEAD
git diff --stat EXECUTION_BASE..HEAD
git status --short
rg -n 'TBD|FIXME|pass$|NotImplementedError' aviato tests README.md docs/guide docs/specifications docs/requirements docs/security
```

Replace `EXECUTION_BASE` with the commit recorded immediately before Task 1. Expected: no whitespace errors, only intended files, a clean worktree, and no newly introduced incomplete implementation markers. Investigate pre-existing matches rather than deleting unrelated content.

- [ ] **Step 3: Run CI-parity commands independently**

Run:

```bash
python -m ruff check .
python -m pytest --cov --cov-report=term-missing
python -m mypy --strict aviato tests
```

Expected: all commands pass with no regression in the repository's enforced coverage threshold.

- [ ] **Step 4: Record final evidence for handoff**

Capture:

- final commit hashes;
- `git status --short` output;
- focused reconcile/drift test counts;
- `./scripts/validate.sh` result;
- strict validation result or the exact optional tools unavailable;
- the fact that no GitHub issue was required or mutated by reconcile tests.

Do not close GitHub issue #115 merely because the implementation exists locally. Let the merge/PR workflow link the actual audit trail, and let a later verified-clean drift scan exercise issue auto-closure.
