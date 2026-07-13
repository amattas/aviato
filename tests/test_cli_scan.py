from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from aviato import cli
from aviato.cli import _scan_has_file_drift, main
from aviato.core.diagnosis import diagnose
from aviato.core.errors import AviatoError
from aviato.core.file_drift_flow import _PROPOSABLE, FileDriftOutcome
from aviato.core.fleet import RepoScan
from aviato.core.scaffold import ScaffoldItem as _ScaffoldItem
from aviato.core.scaffold import scaffold
from aviato.github_platform import GitHubPlatform


def _record_keyword_arguments[**P, R](fn: Callable[P, R], calls: list[dict[str, object]]) -> Callable[P, R]:
    def recording(*args: P.args, **kwargs: P.kwargs) -> R:
        calls.append(dict(kwargs))
        return fn(*args, **kwargs)

    return recording


ScaffoldItem = partial(_ScaffoldItem, input_hash="0" * 64)

PYTHON_DECLARATION = (
    "profile: python-library\nversion: v1\nvariables:\n  distribution-name: acme\n  import-name: acme\n"
)


def test_scan_prints_per_repo_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text(PYTHON_DECLARATION, encoding="utf-8")
    plain = tmp_path / "plain"
    plain.mkdir()

    rc = main(["scan", str(consumer), str(plain)])
    captured = capsys.readouterr()
    # A per-repo error (the plain repo has no declaration) makes the run exit non-zero so CI can
    # gate on it, and the error row goes to stderr so the stdout TSV stays machine-parseable.
    assert rc == 1
    assert "python-library" in captured.out
    assert "missing" in captured.out  # unscaffolded managed files
    assert "ERROR: no declaration" in captured.err  # the plain repo, on stderr
    assert "ERROR" not in captured.out


def test_scan_rejects_invalid_declared_enum_before_fix_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text(
        "profile: node-service\nversion: v0\nvariables:\n  project-name: sample\n  language-variant: ruby\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_propose_file_drift", lambda *args, **kwargs: pytest.fail("opened proposal"))

    rc = main(["scan", str(consumer), "--fix"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "language-variant" in captured.err


def test_scan_fix_preserves_declaration_exit_when_later_proposal_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = tmp_path / "invalid"
    (invalid / ".github").mkdir(parents=True)
    (invalid / ".github" / "aviato.yaml").write_text(
        "profile: node-service\nversion: v0\nvariables:\n  project-name: sample\n  language-variant: ruby\n",
        encoding="utf-8",
    )
    fixable = tmp_path / "fixable"
    (fixable / ".github").mkdir(parents=True)
    (fixable / ".github" / "aviato.yaml").write_text(PYTHON_DECLARATION, encoding="utf-8")

    def fail_proposal(*args: object, **kwargs: object) -> object:
        raise AviatoError("proposal failed")

    monkeypatch.setattr(cli, "_propose_file_drift", fail_proposal)

    rc = main(["scan", str(invalid), str(fixable), "--fix"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "language-variant" in captured.err
    assert "fix ERROR: proposal failed" in captured.err


def test_scan_surfaces_seed_once_divergence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # review #2: the fleet sweep must surface §6.3 seed-once tamper/deletion (not only `doctor`).
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text(PYTHON_DECLARATION, encoding="utf-8")
    # Seed LICENSE (records its hash in the report-only sidecar), then TAMPER it.
    license_item = [ScaffoldItem("LICENSE", "MIT v1\n", "#", seed_once=True)]
    scaffold(consumer, license_item, profile="python-library", version="v1")
    (consumer / "LICENSE").write_text("tampered\n", encoding="utf-8")

    rc = main(["scan", str(consumer)])
    err = capsys.readouterr().err
    assert rc == 0  # divergence is report-only, not an error exit
    assert "seed divergence: LICENSE" in err


@pytest.mark.parametrize(
    ("status", "fixable"),
    [
        ("missing", True),
        ("mergeable-drift", True),  # regression (§5.11): body drift MUST be proposable via --fix
        ("dirty-drift", False),  # operator hand-edited / malformed marker — never auto-fixed
        ("clean", False),
    ],
)
def test_scan_fix_gate_matches_proposable_statuses(status: str, fixable: bool) -> None:
    # The --fix gate must align with file_drift_flow._PROPOSABLE; a stale "drift" literal
    # here previously made --fix silently no-op on mergeable-drift (the common drift case).
    assert _scan_has_file_drift(RepoScan("repo", statuses={"some/file": status})) is fixable


def test_scan_fix_gate_empty_is_not_fixable() -> None:
    assert _scan_has_file_drift(RepoScan("repo")) is False


def test_scan_fix_gate_agrees_with_proposable_set() -> None:
    # The gate must agree with file_drift_flow._PROPOSABLE for EVERY status, so a future
    # proposable status added there cannot silently diverge from what --fix acts on.
    for status in (*_PROPOSABLE, "dirty-drift", "clean"):
        assert _scan_has_file_drift(RepoScan("repo", statuses={"f": status})) is (status in _PROPOSABLE)


def test_scan_fix_proposes_from_clone_not_operator_working_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # review #5: scan --fix must push the proposal from a FRESH CLONE, never the operator's live
    # checkout — open_or_update_proposal does `git switch -C` + `push --force`, which in the live
    # tree would clobber uncommitted work and race a second scan.
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text(PYTHON_DECLARATION, encoding="utf-8")
    # Make .editorconfig mergeable-drift: correct body, stale marker hash → proposable via --fix.
    from aviato.core.composition import resolve_profile
    from aviato.core.registry import Registry
    from aviato.paths import MODULE_SOURCE_ROOT

    rs = resolve_profile(Registry(MODULE_SOURCE_ROOT), "python-library")
    body = Registry(MODULE_SOURCE_ROOT).template_body(next(t for t in rs.templates if t.output_path == ".editorconfig"))
    (consumer / ".editorconfig").write_text(
        f"# aviato:managed profile=python-library version=v1 hash=DEADBEEF\n{body}", encoding="utf-8"
    )

    monkeypatch.setattr(cli, "_version_pin_error", lambda *a, **k: None)  # not under test here
    monkeypatch.setattr(cli, "remote_url", lambda root: "https://github.com/o/r.git")
    diagnosis_calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "diagnose", _record_keyword_arguments(diagnose, diagnosis_calls))

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        assert "clone" in cmd, f"scan --fix ran an unexpected command in/near the operator tree: {cmd}"
        Path(cmd[-1]).mkdir(parents=True, exist_ok=True)  # stand in for the clone
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    captured: dict[str, str] = {}

    def fake_run_file_drift(platform: GitHubPlatform, **kwargs: object) -> FileDriftOutcome:
        captured["workdir"] = str(platform.workdir)
        return FileDriftOutcome(proposed=[".editorconfig"], dirty=[])

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "run_file_drift", fake_run_file_drift)

    rc = main(["scan", str(consumer), "--fix"])
    assert rc == 0
    # The proposal platform's workdir is the temp clone, NOT the operator's repo.
    assert captured["workdir"] != str(consumer)
    assert "aviato-scanfix-" in captured["workdir"]
    expected_inputs = cli._diagnosis_probe_inputs(Registry(MODULE_SOURCE_ROOT), "python-library")
    assert {key: diagnosis_calls[-1][key] for key in expected_inputs} == expected_inputs


def test_scan_fix_blocks_incompatible_version_pin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # §2.6/§5.12: scan --fix must enforce the version-pin gate like drift-report/sync —
    # an incompatible local tool cannot regenerate a consumer's files. Pin at a major the
    # 0.x tool can never satisfy, and assert --fix reports the mismatch (and does not crash).
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text(
        PYTHON_DECLARATION.replace("version: v1", "version: 2.0.0"), encoding="utf-8"
    )
    rc = main(["scan", str(consumer), "--fix"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "version-pin mismatch" in err


def test_scan_surfaces_missing_drift_automation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # finding 33: the fleet sweep runs the FULL §5.4 diagnosis — a consumer with no
    # scheduled drift caller must be flagged, not read as healthy at scale.
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text(PYTHON_DECLARATION, encoding="utf-8")

    rc = main(["scan", str(consumer)])
    err = capsys.readouterr().err
    assert rc == 0
    assert "drift automation: MISSING" in err


def test_scan_audit_lists_open_drift_issues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # finding 36 (§5.11): read-only audit aggregation over the per-repo tracking
    # issues — ephemeral output, no stored inventory (§2.2).
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text(PYTHON_DECLARATION, encoding="utf-8")
    monkeypatch.setattr(cli, "remote_url", lambda root: "git@github.com:o/r.git")
    monkeypatch.setattr(
        cli,
        "gh_json_paginated_optional",
        lambda endpoint, **kw: [{"number": 12, "title": "Settings drift", "updated_at": "2026-06-01T00:00:00Z"}],
    )

    rc = main(["scan", str(consumer), "--audit"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "audit: #12" in out
