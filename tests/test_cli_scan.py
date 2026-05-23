from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from aviato import cli
from aviato.cli import _scan_has_file_drift, main
from aviato.core.file_drift_flow import _PROPOSABLE
from aviato.core.scaffold import ScaffoldItem, scaffold


def test_scan_prints_per_repo_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text("profile: python-library\nversion: v1\n", encoding="utf-8")
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


def test_scan_surfaces_seed_once_divergence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # review #2: the fleet sweep must surface §6.3 seed-once tamper/deletion (not only `doctor`).
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text("profile: python-library\nversion: v1\n", encoding="utf-8")
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
    assert _scan_has_file_drift(SimpleNamespace(statuses={"some/file": status})) is fixable


def test_scan_fix_gate_empty_is_not_fixable() -> None:
    assert _scan_has_file_drift(SimpleNamespace(statuses={})) is False


def test_scan_fix_gate_agrees_with_proposable_set() -> None:
    # The gate must agree with file_drift_flow._PROPOSABLE for EVERY status, so a future
    # proposable status added there cannot silently diverge from what --fix acts on.
    for status in (*_PROPOSABLE, "dirty-drift", "clean"):
        assert _scan_has_file_drift(SimpleNamespace(statuses={"f": status})) is (status in _PROPOSABLE)


def test_scan_fix_proposes_from_clone_not_operator_working_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # review #5: scan --fix must push the proposal from a FRESH CLONE, never the operator's live
    # checkout — open_or_update_proposal does `git switch -C` + `push --force`, which in the live
    # tree would clobber uncommitted work and race a second scan.
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text("profile: python-library\nversion: v1\n", encoding="utf-8")
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

    def fake_run(cmd, **kwargs):
        assert "clone" in cmd, f"scan --fix ran an unexpected command in/near the operator tree: {cmd}"
        Path(cmd[-1]).mkdir(parents=True, exist_ok=True)  # stand in for the clone
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    captured: dict[str, str] = {}

    def fake_run_file_drift(platform, **kwargs):
        captured["workdir"] = str(platform.workdir)
        return SimpleNamespace(proposed=[".editorconfig"], dirty=[])

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "run_file_drift", fake_run_file_drift)

    rc = main(["scan", str(consumer), "--fix"])
    assert rc == 0
    # The proposal platform's workdir is the temp clone, NOT the operator's repo.
    assert captured["workdir"] != str(consumer)
    assert "aviato-scanfix-" in captured["workdir"]


def test_scan_fix_blocks_incompatible_version_pin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # §2.6/§5.12: scan --fix must enforce the version-pin gate like drift-report/sync —
    # an incompatible local tool cannot regenerate a consumer's files. Pin at a major the
    # 0.x tool can never satisfy, and assert --fix reports the mismatch (and does not crash).
    consumer = tmp_path / "c"
    (consumer / ".github").mkdir(parents=True)
    (consumer / ".github" / "aviato.yaml").write_text("profile: python-library\nversion: 2.0.0\n", encoding="utf-8")
    rc = main(["scan", str(consumer), "--fix"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "version-pin mismatch" in err
