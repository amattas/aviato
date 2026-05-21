from __future__ import annotations

from pathlib import Path

import pytest

from aviato.core.diagnosis import ExpectedArtifact, diagnose
from aviato.core.errors import BootstrapError
from aviato.core.scaffold import ScaffoldItem, scaffold


def _scaffold_one(root: Path, output: str, body: str) -> None:
    scaffold(root, [ScaffoldItem(output, body, "#", False)], profile="p", version="v1")


def test_clean_when_body_matches(tmp_path: Path) -> None:
    _scaffold_one(tmp_path, "cfg.py", "X = 1\n")
    report = diagnose(tmp_path, [ExpectedArtifact("cfg.py", "X = 1\n")])
    assert report.statuses["cfg.py"] == "clean"


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


def test_bootstrap_declaration_rejected_outside_library(tmp_path: Path) -> None:
    with pytest.raises(BootstrapError):
        diagnose(tmp_path, [], bootstrap_declared=True, is_library=False)


def test_bootstrap_declaration_allowed_in_library(tmp_path: Path) -> None:
    report = diagnose(tmp_path, [], bootstrap_declared=True, is_library=True)
    assert report.statuses == {}
