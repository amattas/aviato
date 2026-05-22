from __future__ import annotations

from pathlib import Path

from aviato.core.marker import content_hash
from aviato.core.scaffold import ScaffoldItem, read_sidecar, scaffold


def test_writes_managed_file_with_marker_atomically(tmp_path: Path) -> None:
    plan = [ScaffoldItem(output="cfg.py", body="X = 1\n", comment="#", seed_once=False)]
    result = scaffold(tmp_path, plan, profile="p", version="v1")
    text = (tmp_path / "cfg.py").read_text()
    assert text.startswith("# aviato:managed profile=p version=v1 hash=")
    assert "X = 1" in text
    assert result.written == ["cfg.py"]


def test_creates_parent_directories(tmp_path: Path) -> None:
    plan = [ScaffoldItem(output="a/b/cfg.py", body="X = 1\n", comment="#", seed_once=False)]
    scaffold(tmp_path, plan, profile="p", version="v1")
    assert (tmp_path / "a" / "b" / "cfg.py").is_file()


def test_idempotent_on_clean_tree(tmp_path: Path) -> None:
    plan = [ScaffoldItem("cfg.py", "X = 1\n", "#", False)]
    scaffold(tmp_path, plan, profile="p", version="v1")
    first = (tmp_path / "cfg.py").read_text()
    result = scaffold(tmp_path, plan, profile="p", version="v1")
    assert (tmp_path / "cfg.py").read_text() == first
    assert result.unchanged == ["cfg.py"]
    assert result.written == []


def test_refuses_to_overwrite_unmanaged_file_unless_forced(tmp_path: Path) -> None:
    (tmp_path / "cfg.py").write_text("hand written\n")
    plan = [ScaffoldItem("cfg.py", "X = 1\n", "#", False)]
    result = scaffold(tmp_path, plan, profile="p", version="v1")
    assert "cfg.py" in result.skipped_unmanaged
    assert (tmp_path / "cfg.py").read_text() == "hand written\n"

    scaffold(tmp_path, plan, profile="p", version="v1", force=True)
    assert "X = 1" in (tmp_path / "cfg.py").read_text()


def test_refuses_to_overwrite_malformed_marker_unless_forced(tmp_path: Path) -> None:
    (tmp_path / "cfg.py").write_text("# aviato:managed profile=p\nbody\n")  # malformed
    plan = [ScaffoldItem("cfg.py", "X = 1\n", "#", False)]
    result = scaffold(tmp_path, plan, profile="p", version="v1")
    assert "cfg.py" in result.skipped_unmanaged


def test_refuses_to_overwrite_hand_edited_managed_file_unless_forced(tmp_path: Path) -> None:
    # scaffold, then hand-edit the body while leaving the (now-stale) marker line
    scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 1\n", "#", False)], profile="p", version="v1")
    text = (tmp_path / "cfg.py").read_text()
    marker_line = text.splitlines()[0]
    (tmp_path / "cfg.py").write_text(marker_line + "\nX = HAND_EDITED\n")

    result = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 2\n", "#", False)], profile="p", version="v1")
    assert "cfg.py" in result.skipped_modified
    assert "HAND_EDITED" in (tmp_path / "cfg.py").read_text()  # not clobbered

    forced = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 2\n", "#", False)], profile="p", version="v1", force=True)
    assert "cfg.py" in forced.written
    assert "X = 2" in (tmp_path / "cfg.py").read_text()


def test_refuses_to_overwrite_marker_from_different_profile_unless_forced(tmp_path: Path) -> None:
    # §5.3/§5.4 one posture: a valid marker stamped for a DIFFERENT profile is dirty-drift in
    # diagnosis, so scaffold must NOT silently regenerate it either (one profile per repo, §3).
    scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 1\n", "#", False)], profile="other-profile", version="v1")
    before = (tmp_path / "cfg.py").read_text()

    # Sync under profile "p" with a CHANGED body — without the guard this would overwrite.
    result = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 2\n", "#", False)], profile="p", version="v1")
    assert result.skipped_foreign == ["cfg.py"]
    assert result.written == []
    assert (tmp_path / "cfg.py").read_text() == before  # foreign-profile file untouched

    forced = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 2\n", "#", False)], profile="p", version="v1", force=True)
    assert forced.written == ["cfg.py"]
    assert "profile=p " in (tmp_path / "cfg.py").read_text()


def test_refuses_to_overwrite_marker_with_unknown_version_unless_forced(tmp_path: Path) -> None:
    # §5.4: a marker recording an unknown/unparseable version cannot be reasoned about for
    # compatibility, so scaffold mirrors diagnosis dirty-drift and never silently regenerates it.
    (tmp_path / "cfg.py").write_text("# aviato:managed profile=p version=garbage hash=DEADBEEF\nX = 1\n")
    result = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 2\n", "#", False)], profile="p", version="v1")
    assert result.skipped_foreign == ["cfg.py"]
    assert "X = 1" in (tmp_path / "cfg.py").read_text()  # not clobbered

    forced = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 2\n", "#", False)], profile="p", version="v1", force=True)
    assert "cfg.py" in forced.written


def test_stale_marker_correct_body_is_regenerated_not_skipped(tmp_path: Path) -> None:
    # body already matches desired but marker hash is stale: scaffold must regenerate
    # (refresh the marker), agreeing with diagnosis "mergeable" rather than skipping
    (tmp_path / "cfg.py").write_text("# aviato:managed profile=p version=v1 hash=DEADBEEF\nX = 1\n")
    result = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 1\n", "#", False)], profile="p", version="v1")
    assert "cfg.py" in result.written
    assert result.skipped_modified == []
    assert "hash=DEADBEEF" not in (tmp_path / "cfg.py").read_text()  # marker refreshed


def test_regenerates_managed_file_when_body_changes(tmp_path: Path) -> None:
    scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 1\n", "#", False)], profile="p", version="v1")
    result = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 2\n", "#", False)], profile="p", version="v1")
    assert result.written == ["cfg.py"]
    assert "X = 2" in (tmp_path / "cfg.py").read_text()


def test_seed_once_writes_when_absent_records_sidecar_and_never_overwrites(tmp_path: Path) -> None:
    plan = [ScaffoldItem("Dockerfile", "FROM x\n", "#", seed_once=True)]
    result = scaffold(tmp_path, plan, profile="p", version="v1")
    assert (tmp_path / "Dockerfile").read_text() == "FROM x\n"  # no marker
    assert result.seeded == ["Dockerfile"]

    sidecar = read_sidecar(tmp_path)
    assert sidecar["Dockerfile"] == content_hash("FROM x\n")  # report-only integrity hash

    (tmp_path / "Dockerfile").write_text("FROM y\n")
    result2 = scaffold(tmp_path, plan, profile="p", version="v1")
    assert (tmp_path / "Dockerfile").read_text() == "FROM y\n"  # never overwritten
    assert result2.seeded == []
