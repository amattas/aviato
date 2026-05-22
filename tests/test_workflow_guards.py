from __future__ import annotations

import yaml

from aviato.paths import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCAFFOLD_FILES = REPO_ROOT / "aviato" / "library" / "scaffold" / "files"


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def test_docs_callers_resolve_bare_aviato_release_tags() -> None:
    # G2/§13.3: Aviato tags releases as BARE SemVer (`1.2.3`); policy.yml rejects a
    # v-prefix. The docs deploy callers gate on `git tag --list <glob>` to detect a
    # release commit. A v-prefixed glob (`v[0-9]*...`) can NEVER match a real Aviato tag,
    # so docs deploy would silently never run — and these callers have no template/parity
    # coverage, so nothing else catches it. Guard the tag matcher directly.
    docs_callers = sorted(SCAFFOLD_FILES.glob("wf-docs-*.yml"))
    assert docs_callers, "no docs caller scaffolds found"
    for caller in docs_callers:
        body = caller.read_text(encoding="utf-8")
        assert "--list" in body, f"{caller.name} no longer resolves a release tag via git tag --list"
        assert "'v[0-9]" not in body, (
            f"{caller.name} matches a v-prefixed tag glob, which no Aviato release tag ever uses "
            f"(policy rejects the v-prefix) — docs deploy would never trigger"
        )
        assert "--list '[0-9]" in body, f"{caller.name} must match bare-SemVer release tags"


def test_consumer_automation_jitters_scheduled_runs() -> None:
    # §5.5/§8.x: the scheduled drift/report caller MUST jitter before doing work so a
    # fleet sharing one cron does not stampede the hosting platform. Guard the jitter
    # step structurally so a refactor cannot silently drop it (it is otherwise only
    # exercised by a live scheduled run, which the test suite does not perform).
    wf = _load("reusable-consumer-automation.yml")
    runs = [
        step.get("run", "")
        for job in wf["jobs"].values()
        if isinstance(job, dict)
        for step in job.get("steps", [])
        if isinstance(step, dict)
    ]
    assert any("sleep" in run and "RANDOM" in run for run in runs), "no anti-stampede jitter step found"


def test_security_baseline_retains_fail_closed_structure() -> None:
    # §5.14/§8.16: the security baseline must (a) probe the findings-upload privilege and
    # hard-fail without it, (b) run each scan only after that probe, (c) emit a per-run
    # heartbeat even on zero findings, and (d) gate on required scans. This is the one
    # place a refactor could silently remove the fail-closed posture; the live gate is
    # operator-verified, so guard the protective structure statically.
    wf = _load("reusable-security-baseline.yml")
    jobs = wf["jobs"]

    assert "privilege-probe" in jobs, "missing runtime findings-upload privilege probe"
    assert "heartbeat" in jobs, "missing per-run heartbeat job"

    scan_jobs = ["codeql", "dependency-review", "dependency-scan", "secret-scan"]
    for name in scan_jobs:
        assert name in jobs, f"missing scan job {name}"
        assert jobs[name].get("needs") == "privilege-probe", f"{name} must run after the privilege probe"

    heartbeat_needs = jobs["heartbeat"].get("needs", [])
    for name in scan_jobs:
        assert name in heartbeat_needs, f"heartbeat must depend on {name} so a skipped scan is detectable"

    gate_steps = [step.get("name", "") for step in jobs["heartbeat"].get("steps", []) if isinstance(step, dict)]
    assert any("Gate" in name for name in gate_steps), "missing 'Gate on required scans' step"
