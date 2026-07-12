from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest

from aviato.core.diagnosis import ExpectedArtifact, diagnose
from aviato.core.errors import PathConfinementError
from aviato.core.marker import content_hash, parse_marker_from_text
from aviato.core.scaffold import ScaffoldItem as _ScaffoldItem
from aviato.core.scaffold import SeedSidecar, read_sidecar, scaffold

INPUT_HASH = "a" * 64
ScaffoldItem = partial(_ScaffoldItem, input_hash=INPUT_HASH)


def test_scaffold_rejects_symlinked_parent(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / ".github").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathConfinementError, match=r"write scaffold output.*\.github/workflows/ci\.yml"):
        scaffold(
            tmp_path,
            [ScaffoldItem(".github/workflows/ci.yml", "name: ci\n", "#")],
            profile="p",
            version="1",
        )
    assert not (outside / "workflows/ci.yml").exists()


def test_writes_managed_file_with_marker_atomically(tmp_path: Path) -> None:
    plan = [ScaffoldItem(output="cfg.py", body="X = 1\n", comment="#", seed_once=False, input_hash=INPUT_HASH)]
    result = scaffold(tmp_path, plan, profile="p", version="v1")
    text = (tmp_path / "cfg.py").read_text()
    assert text.startswith("# aviato:managed profile=p version=v1 hash=")
    assert "X = 1" in text
    assert result.written == ["cfg.py"]


def test_clean_legacy_marker_is_restamped_once_without_changing_body(tmp_path: Path) -> None:
    body = "X = 1\n"
    (tmp_path / "cfg.py").write_text(
        f"# aviato:managed profile=p version=v1 hash={content_hash(body)}\n{body}", encoding="utf-8"
    )
    item = ScaffoldItem("cfg.py", body, "#", False, input_hash=INPUT_HASH)
    expected = ExpectedArtifact("cfg.py", body, False, input_hash=INPUT_HASH)

    assert diagnose(tmp_path, [expected], profile="p").statuses["cfg.py"] == "mergeable-drift"
    result = scaffold(tmp_path, [item], profile="p", version="v1")

    assert result.written == ["cfg.py"]
    text = (tmp_path / "cfg.py").read_text(encoding="utf-8")
    assert text.endswith(body)
    marker = parse_marker_from_text(text)
    assert marker is not None and marker.input_hash == INPUT_HASH
    assert diagnose(tmp_path, [expected], profile="p").statuses["cfg.py"] == "clean"


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


def test_force_restamps_foreign_profile_marker_even_when_body_matches(tmp_path: Path) -> None:
    # A forceful profile migration must refresh the marker even if the rendered body is
    # unchanged; otherwise the next diagnosis still classifies the file as foreign drift.
    item = ScaffoldItem("cfg.py", "X = 1\n", "#", False)
    scaffold(tmp_path, [item], profile="old-profile", version="v1")

    forced = scaffold(tmp_path, [item], profile="new-profile", version="v1", force=True)
    text = (tmp_path / "cfg.py").read_text()
    assert forced.written == ["cfg.py"]
    assert "profile=new-profile " in text
    assert "profile=old-profile " not in text


def test_refuses_to_overwrite_marker_with_unknown_version_unless_forced(tmp_path: Path) -> None:
    # §5.4: a marker recording an unknown/unparseable version cannot be reasoned about for
    # compatibility, so scaffold mirrors diagnosis dirty-drift and never silently regenerates it.
    (tmp_path / "cfg.py").write_text("# aviato:managed profile=p version=garbage hash=DEADBEEF\nX = 1\n")
    result = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 2\n", "#", False)], profile="p", version="v1")
    assert result.skipped_foreign == ["cfg.py"]
    assert "X = 1" in (tmp_path / "cfg.py").read_text()  # not clobbered

    forced = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 2\n", "#", False)], profile="p", version="v1", force=True)
    assert "cfg.py" in forced.written


def test_version_only_change_restamps_marker_not_left_stale(tmp_path: Path) -> None:
    # §5.12: a re-pin moves the version; even when the body is unchanged the marker MUST be
    # restamped to the new pin (the drift hash excludes the version, so without this the marker
    # would silently keep the OLD version, breaking the §2.6 gate after a downgrade).
    scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 1\n", "#", False)], profile="p", version="1")
    assert "version=1 " in (tmp_path / "cfg.py").read_text()

    result = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 1\n", "#", False)], profile="p", version="2")
    assert result.written == ["cfg.py"]  # restamped, not left "unchanged"
    assert "version=2 " in (tmp_path / "cfg.py").read_text()

    # Idempotent: re-running at the SAME version is a no-op (no churn).
    again = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 1\n", "#", False)], profile="p", version="2")
    assert again.written == [] and again.unchanged == ["cfg.py"]


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
    assert sidecar == SeedSidecar("ok", {"Dockerfile": content_hash("FROM x\n")})

    (tmp_path / "Dockerfile").write_text("FROM y\n")
    result2 = scaffold(tmp_path, plan, profile="p", version="v1")
    assert (tmp_path / "Dockerfile").read_text() == "FROM y\n"  # never overwritten
    assert result2.seeded == []


def test_seed_once_missing_sidecar_fails_closed_before_any_managed_write(tmp_path: Path) -> None:
    plan = [ScaffoldItem("Dockerfile", "FROM x\n", "#", seed_once=True)]
    scaffold(tmp_path, plan, profile="p", version="v1")
    (tmp_path / ".github" / "aviato.seed.json").unlink()  # operator/attacker deletes the record
    assert read_sidecar(tmp_path) == SeedSidecar("missing", {})

    result = scaffold(
        tmp_path,
        [ScaffoldItem("managed.txt", "managed\n", "#"), *plan],
        profile="p",
        version="v1",
    )
    assert result.seed_integrity_unknown is True
    assert not (tmp_path / "managed.txt").exists()
    assert not (tmp_path / ".github" / "aviato.seed.json").exists()


def test_corrupt_sidecar_fails_closed_before_any_managed_write(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "aviato.seed.json").write_text("{ this is not json", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM operator\n", encoding="utf-8")
    assert read_sidecar(tmp_path) == SeedSidecar("corrupt", {})
    result = scaffold(
        tmp_path,
        [ScaffoldItem("cfg.py", "X = 1\n", "#"), ScaffoldItem("Dockerfile", "FROM x\n", "#", True)],
        profile="p",
        version="v1",
    )
    assert result.seed_integrity_unknown is True
    assert not (tmp_path / "cfg.py").exists()
    assert (tmp_path / ".github" / "aviato.seed.json").read_text() == "{ this is not json"


def test_sidecar_with_invalid_hash_record_is_corrupt(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "aviato.seed.json").write_text('{"Dockerfile": "not-a-sha256"}\n', encoding="utf-8")

    assert read_sidecar(tmp_path) == SeedSidecar("corrupt", {})


def test_sidecar_with_duplicate_path_record_is_corrupt(tmp_path: Path) -> None:
    digest = content_hash("FROM x\n")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "aviato.seed.json").write_text(
        f'{{"Dockerfile": "{digest}", "Dockerfile": "{digest}"}}\n', encoding="utf-8"
    )

    assert read_sidecar(tmp_path) == SeedSidecar("corrupt", {})


def test_incomplete_sidecar_fails_closed_before_any_write(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "aviato.seed.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM operator\n", encoding="utf-8")

    result = scaffold(
        tmp_path,
        [ScaffoldItem("managed.txt", "managed\n", "#"), ScaffoldItem("Dockerfile", "FROM x\n", "#", True)],
        profile="p",
        version="v1",
    )

    assert result.seed_integrity_unknown is True
    assert not (tmp_path / "managed.txt").exists()
    assert read_sidecar(tmp_path) == SeedSidecar("ok", {})


@pytest.mark.parametrize("sidecar_body", ["{ corrupt", "{}\n"])
def test_unknown_sidecar_with_absent_expected_seed_fails_closed(tmp_path: Path, sidecar_body: str) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "aviato.seed.json").write_text(sidecar_body, encoding="utf-8")

    result = scaffold(
        tmp_path,
        [ScaffoldItem("managed.txt", "managed\n", "#"), ScaffoldItem("Dockerfile", "FROM x\n", "#", True)],
        profile="p",
        version="v1",
    )

    assert result.seed_integrity_unknown is True
    assert not (tmp_path / "managed.txt").exists()
    assert not (tmp_path / "Dockerfile").exists()
    assert (tmp_path / ".github" / "aviato.seed.json").read_text(encoding="utf-8") == sidecar_body


def test_missing_sidecar_with_absent_seed_creates_seed_and_initial_record(tmp_path: Path) -> None:
    result = scaffold(
        tmp_path,
        [ScaffoldItem("Dockerfile", "FROM x\n", "#", True)],
        profile="p",
        version="v1",
    )
    assert result.seed_integrity_unknown is False
    assert result.seeded == ["Dockerfile"]
    assert read_sidecar(tmp_path) == SeedSidecar("ok", {"Dockerfile": content_hash("FROM x\n")})


def test_explicit_rebaseline_replaces_obsolete_records_with_current_seed_set(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "aviato.seed.json").write_text('{"obsolete": "old"}\n', encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM operator\n", encoding="utf-8")

    result = scaffold(
        tmp_path,
        [ScaffoldItem("Dockerfile", "FROM x\n", "#", True)],
        profile="p",
        version="v1",
        baseline_existing_seeds=True,
    )

    assert result.baselined == ["Dockerfile"]
    assert read_sidecar(tmp_path) == SeedSidecar("ok", {"Dockerfile": content_hash("FROM operator\n")})


def test_non_utf8_managed_file_is_skipped_not_crashed(tmp_path: Path) -> None:
    # review #6: a non-UTF-8 file at a managed path can't carry a marker → operator-owned; scaffold
    # must skip it (never regenerate, never crash a fleet sync with a raw UnicodeDecodeError).
    (tmp_path / "cfg.py").write_bytes(b"\xff\xfe\x00 binary")
    result = scaffold(tmp_path, [ScaffoldItem("cfg.py", "X = 1\n", "#", False)], profile="p", version="v1")
    assert result.skipped_unmanaged == ["cfg.py"]
    assert (tmp_path / "cfg.py").read_bytes() == b"\xff\xfe\x00 binary"  # untouched


def test_atomic_write_preserves_existing_mode(tmp_path: Path) -> None:
    # finding 22: the mkstemp temp file is 0600; os.replace previously demoted an
    # existing file's permissions (e.g. dropping +x from a seeded helper script).
    from aviato.core.scaffold import atomic_write

    target = tmp_path / "script.sh"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o755)
    atomic_write(tmp_path, "script.sh", "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert target.stat().st_mode & 0o777 == 0o755


def test_atomic_write_new_files_honor_umask(tmp_path: Path) -> None:
    import os

    from aviato.core.scaffold import atomic_write

    previous = os.umask(0o022)
    try:
        target = tmp_path / "fresh.txt"
        atomic_write(tmp_path, "fresh.txt", "x")
        assert target.stat().st_mode & 0o777 == 0o644
    finally:
        os.umask(previous)
