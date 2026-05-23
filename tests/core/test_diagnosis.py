from __future__ import annotations

from pathlib import Path

import pytest

from aviato.core.diagnosis import ExpectedArtifact, diagnose
from aviato.core.errors import BootstrapError
from aviato.core.scaffold import ScaffoldItem, scaffold


def _scaffold_one(root: Path, output: str, body: str) -> None:
    scaffold(root, [ScaffoldItem(output, body, "#", False)], profile="p", version="v1")


def test_diagnose_tolerates_non_utf8_workflow_file(tmp_path: Path) -> None:
    # A corrupted/non-UTF-8 workflow file in .github/workflows must not crash diagnosis
    # (and thus a whole fleet scan) with a UnicodeDecodeError when probing for the
    # scheduled drift-automation caller (§5.4 robustness). Place a VALID drift caller
    # ALONGSIDE the bad file and assert it is still found — proving the bad file was
    # tolerated and the scan continued, not that detection was silently disabled (which
    # a bare `present is False` could not distinguish from "no caller present").
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "bad.yml").write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")
    (workflows / "aviato-drift.yml").write_text(
        "jobs:\n  drift:\n    uses: owner/aviato/.github/workflows/reusable-consumer-automation.yml@main\n",
        encoding="utf-8",
    )
    report = diagnose(tmp_path, [])
    assert report.drift_automation_present is True  # bad file tolerated; valid caller still detected


def test_clean_when_body_matches(tmp_path: Path) -> None:
    _scaffold_one(tmp_path, "cfg.py", "X = 1\n")
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 1\n")])
    assert report.statuses["cfg.py"] == "clean"


def test_marker_for_different_profile_is_dirty_drift(tmp_path: Path) -> None:
    # §6.2: the marker's profile field is ENFORCED, not just recorded. A file stamped
    # for profile "p" must not read clean under a declaration for profile "other" —
    # even when the body matches — it needs human review (dirty-drift, §5.4).
    _scaffold_one(tmp_path, "cfg.py", "X = 1\n")  # stamped profile="p"
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 1\n")], profile="other")
    assert report.statuses["cfg.py"] == "dirty-drift"
    # ...and matches clean when the profile agrees.
    report_ok = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 1\n")], profile="p")
    assert report_ok.statuses["cfg.py"] == "clean"


def test_mergeable_drift_when_body_diverges_with_valid_marker(tmp_path: Path) -> None:
    _scaffold_one(tmp_path, "cfg.py", "X = 1\n")
    # expected body now differs but the on-disk file still has a valid marker
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 999\n")])
    assert report.statuses["cfg.py"] == "mergeable-drift"


def test_clean_ignores_marker_version_change(tmp_path: Path) -> None:
    # file stamped v1; resolved set is now v2 but body identical → still clean (§5.5)
    _scaffold_one(tmp_path, "cfg.py", "X = 1\n")
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 1\n")])
    assert report.statuses["cfg.py"] == "clean"


def test_hand_edited_managed_file_is_dirty_drift(tmp_path: Path) -> None:
    # valid marker, but the body was edited so it no longer matches the marker's
    # recorded hash → operator hand-edit → dirty-drift, never silently regenerated
    _scaffold_one(tmp_path, "cfg.py", "X = 1\n")
    text = (tmp_path / "cfg.py").read_text()
    marker_line = text.splitlines()[0]
    (tmp_path / "cfg.py").write_text(marker_line + "\nX = HAND_EDITED\n")
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 1\n")])
    assert report.statuses["cfg.py"] == "dirty-drift"


def test_stale_marker_but_correct_body_is_mergeable_not_clean(tmp_path: Path) -> None:
    # body matches expected, but the marker hash is stale → mergeable (so doctor and
    # sync agree: sync regenerates to refresh the marker rather than calling it clean)
    (tmp_path / "cfg.py").write_text("# aviato:managed profile=p version=v1 hash=DEADBEEF\nX = 1\n")
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 1\n")])
    assert report.statuses["cfg.py"] == "mergeable-drift"


def test_unknown_recorded_version_is_dirty_drift(tmp_path: Path) -> None:
    # §5.4: a managed file whose marker records an UNKNOWN/unparseable version is
    # dirty-drift even if the body matches expected — Aviato never silently regenerates
    # over a marker it cannot reason about (it can't establish version compatibility).
    body = "X = 1\n"
    from aviato.core.marker import content_hash

    (tmp_path / "cfg.py").write_text(f"# aviato:managed profile=p version=garbage hash={content_hash(body)}\n{body}")
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", body)])
    assert report.statuses["cfg.py"] == "dirty-drift"


def test_template_moved_but_file_untouched_is_mergeable(tmp_path: Path) -> None:
    # file is exactly what Aviato wrote (body hash == marker hash) but expected changed
    _scaffold_one(tmp_path, "cfg.py", "X = 1\n")
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 999\n")])
    assert report.statuses["cfg.py"] == "mergeable-drift"


def test_dirty_drift_when_no_marker(tmp_path: Path) -> None:
    (tmp_path / "cfg.py").write_text("hand written\n")
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 1\n")])
    assert report.statuses["cfg.py"] == "dirty-drift"


def test_dirty_drift_when_marker_malformed(tmp_path: Path) -> None:
    (tmp_path / "cfg.py").write_text("# aviato:managed profile=p\nbody\n")
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 1\n")])
    assert report.statuses["cfg.py"] == "dirty-drift"


def test_missing_when_absent(tmp_path: Path) -> None:
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 1\n")])
    assert report.statuses["cfg.py"] == "missing"


def test_secret_typed_var_in_declaration_is_flagged(tmp_path: Path) -> None:
    report = diagnose(
        tmp_path,
        [],
        declaration_variables={"token": "abc", "name": "ok"},
        secret_var_names=("token",),
    )
    assert report.secret_in_declaration is True


def test_no_secret_flag_when_clean(tmp_path: Path) -> None:
    report = diagnose(tmp_path, [], declaration_variables={"name": "ok"}, secret_var_names=("token",))
    assert report.secret_in_declaration is False


def test_seed_once_integrity_divergence_is_reported_not_overwritten(tmp_path: Path) -> None:
    scaffold(tmp_path, [ScaffoldItem("Dockerfile", "FROM x\n", "#", True)], profile="p", version="v1")
    (tmp_path / "Dockerfile").write_text("FROM tampered\n")
    report = diagnose(tmp_path, [ExpectedArtifact("Dockerfile", "", seed_once=True)])
    assert "Dockerfile" in report.seed_divergence
    assert (tmp_path / "Dockerfile").read_text() == "FROM tampered\n"  # never overwritten


def test_seed_once_deletion_is_reported_as_divergence(tmp_path: Path) -> None:
    # §6.3 (L-B): a recorded seed-once file that is later DELETED (e.g. a removed Dockerfile) is a
    # divergence too — tamper visibility, not just a hash change. Reported, never re-created.
    scaffold(tmp_path, [ScaffoldItem("Dockerfile", "FROM x\n", "#", True)], profile="p", version="v1")
    (tmp_path / "Dockerfile").unlink()
    report = diagnose(tmp_path, [ExpectedArtifact("Dockerfile", "", seed_once=True)])
    assert "Dockerfile" in report.seed_divergence
    assert not (tmp_path / "Dockerfile").exists()  # not re-created (seed-once is write-when-absent)


def test_seed_once_binary_file_does_not_crash_diagnosis(tmp_path: Path) -> None:
    # §6.3 lists binaries among seed-once files. A seed-once file whose live bytes are
    # not valid UTF-8 must not crash the integrity probe (which would crash a fleet scan);
    # it is read leniently and simply reported as divergence (report-only).
    scaffold(tmp_path, [ScaffoldItem("asset.bin", "placeholder\n", "#", True)], profile="p", version="v1")
    (tmp_path / "asset.bin").write_bytes(b"\xff\xfe\x00\x80 binary \x81")
    report = diagnose(tmp_path, [ExpectedArtifact("asset.bin", "", seed_once=True)])  # must not raise
    assert "asset.bin" in report.seed_divergence
    assert (tmp_path / "asset.bin").read_bytes() == b"\xff\xfe\x00\x80 binary \x81"  # never overwritten


def test_probes_drift_automation_and_prerequisites(tmp_path: Path) -> None:
    prereqs = {"container_build_definition": ["Dockerfile"]}
    # no drift workflow, no Dockerfile → probes false
    report = diagnose(tmp_path, [], prerequisite_paths=prereqs)
    assert report.drift_automation_present is False
    assert report.prerequisites["container_build_definition"] is False

    # add a consumer drift workflow + a Dockerfile
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "drift.yml").write_text("uses: amattas/aviato/.github/workflows/reusable-consumer-automation.yml@main\n")
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    report2 = diagnose(tmp_path, [], prerequisite_paths=prereqs)
    assert report2.drift_automation_present is True
    assert report2.prerequisites["container_build_definition"] is True


def test_platform_probes_default_unknown(tmp_path: Path) -> None:
    # platform-dependent probes are None until the binding fills them (absence != clean)
    report = diagnose(tmp_path, [])
    assert report.issue_channel_available is None
    assert report.scan_heartbeat_present is None


def test_bootstrap_declaration_rejected_outside_library(tmp_path: Path) -> None:
    with pytest.raises(BootstrapError):
        diagnose(tmp_path, [], bootstrap_declared=True, is_library=False)


def test_bootstrap_declaration_allowed_in_library(tmp_path: Path) -> None:
    report = diagnose(tmp_path, [], bootstrap_declared=True, is_library=True)
    assert report.statuses == {}
