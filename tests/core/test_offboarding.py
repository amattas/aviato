from __future__ import annotations

from pathlib import Path

from aviato.core.offboarding import offboard
from aviato.core.scaffold import ScaffoldItem, scaffold


def _setup_consumer(root: Path) -> None:
    github = root / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text("profile: python-library\nversion: v1\n", encoding="utf-8")
    scaffold(root, [ScaffoldItem("ruff.toml", "line-length = 120\n", "#", False)], profile="p", version="v1")


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
