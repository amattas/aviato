from __future__ import annotations

from pathlib import Path

from aviato.core.offboarding import offboard
from aviato.core.scaffold import ScaffoldItem, scaffold


def _setup_consumer(root: Path) -> None:
    github = root / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: v1\n", encoding="utf-8")
    scaffold(root, [ScaffoldItem("ruff.toml", "line-length = 120\n", "#", False)], profile="p", version="v1")


def test_offboard_skips_non_utf8_file_instead_of_crashing(tmp_path: Path) -> None:
    # A non-UTF-8 file cannot carry an Aviato marker (markers are UTF-8). It is operator-
    # owned: skip it, never abort the whole offboard with UnicodeDecodeError mid-classify.
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe not valid utf-8")
    result = offboard(tmp_path, ["blob.bin"], keep_files=True)
    assert "blob.bin" not in result.stripped
    assert "blob.bin" not in result.removed
    assert (tmp_path / "blob.bin").exists()  # left untouched


def test_keep_files_strips_markers_and_deletes_declaration(tmp_path: Path) -> None:
    _setup_consumer(tmp_path)
    result = offboard(tmp_path, ["ruff.toml"], keep_files=True)
    text = (tmp_path / "ruff.toml").read_text()
    assert "aviato:managed" not in text
    assert "line-length = 120" in text
    assert result.stripped == ["ruff.toml"]
    assert result.declaration_removed is True
    assert not (tmp_path / ".github" / "aviato.yaml").exists()


def test_remove_files_deletes_managed_files(tmp_path: Path) -> None:
    _setup_consumer(tmp_path)
    result = offboard(tmp_path, ["ruff.toml"], keep_files=False)
    assert not (tmp_path / "ruff.toml").exists()
    assert result.removed == ["ruff.toml"]


def test_offboarding_carries_baseline_removal_warning(tmp_path: Path) -> None:
    _setup_consumer(tmp_path)
    result = offboard(tmp_path, ["ruff.toml"], keep_files=True)
    assert "security baseline" in result.warning.lower()


def test_unmanaged_file_is_not_stripped(tmp_path: Path) -> None:
    _setup_consumer(tmp_path)
    (tmp_path / "hand.txt").write_text("mine\n")
    result = offboard(tmp_path, ["hand.txt"], keep_files=True)
    assert (tmp_path / "hand.txt").read_text() == "mine\n"
    assert result.stripped == []


def test_keep_files_still_deletes_automation_workflows(tmp_path: Path) -> None:
    # §5.13: even in keep-files mode, the consumer automation caller workflows must be
    # DELETED, not just marker-stripped — a stripped-but-present workflow keeps running,
    # which would leave the §2.13 baseline / drift automation active after offboarding.
    _setup_consumer(tmp_path)
    wf = ".github/workflows/aviato-drift.yml"
    scaffold(tmp_path, [ScaffoldItem(wf, "on: schedule\n", "#", False)], profile="p", version="v1")
    ci = ".github/workflows/aviato-ci.yml"
    scaffold(tmp_path, [ScaffoldItem(ci, "on: push\n", "#", False)], profile="p", version="v1")

    result = offboard(tmp_path, ["ruff.toml", wf, ci], keep_files=True)

    # Passive config is kept (marker stripped); automation workflows are deleted.
    assert (tmp_path / "ruff.toml").exists()
    assert "ruff.toml" in result.stripped
    assert not (tmp_path / wf).exists()
    assert not (tmp_path / ci).exists()
    assert wf in result.removed
    assert ci in result.removed


def test_offboard_fails_closed_on_unmarked_automation_workflow(tmp_path: Path) -> None:
    # N3: an automation workflow that exists but carries no Aviato marker must NOT be silently
    # skipped and then orphaned — removing the declaration would leave it running unmanaged. Fail
    # closed before any mutation; the declaration must remain.
    import pytest

    from aviato.core.errors import AviatoError

    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "aviato-ci.yml").write_text("name: ci\non: push\n", encoding="utf-8")  # no marker
    declaration = tmp_path / ".github" / "aviato.yaml"
    declaration.write_text("profile: python-library\n", encoding="utf-8")
    with pytest.raises(AviatoError):
        offboard(tmp_path, [".github/workflows/aviato-ci.yml"], keep_files=False)
    assert declaration.is_file()  # fail-closed: declaration not removed
