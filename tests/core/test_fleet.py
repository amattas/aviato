from __future__ import annotations

from pathlib import Path

from aviato.core.fleet import scan_fleet
from aviato.core.onboarding import materialize_items
from aviato.core.registry import Registry
from aviato.core.scaffold import scaffold
from aviato.paths import MODULE_SOURCE_ROOT


def _make_consumer(root: Path, *, scaffold_all: bool) -> None:
    github = root / ".github"
    github.mkdir(parents=True)
    (github / "aviato.yaml").write_text("profile: python-library\nversion: v1\n", encoding="utf-8")
    if scaffold_all:
        reg = Registry(MODULE_SOURCE_ROOT)
        items = materialize_items(reg, "python-library", variables={})
        scaffold(root, items, profile="python-library", version="v1")


def test_scan_aggregates_per_repo_status(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    _make_consumer(a, scaffold_all=True)
    _make_consumer(b, scaffold_all=False)

    scans = scan_fleet([a, b], Registry(MODULE_SOURCE_ROOT))
    by_path = {Path(s.path).name: s for s in scans}

    # fully scaffolded repo: managed files clean
    assert all(status == "clean" for status in by_path["a"].statuses.values())
    # unscaffolded repo: managed files missing
    assert any(status == "missing" for status in by_path["b"].statuses.values())


def test_scan_reports_repo_without_declaration(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    scans = scan_fleet([plain], Registry(MODULE_SOURCE_ROOT))
    assert scans[0].error is not None
    assert scans[0].statuses == {}


def test_scan_is_read_only(tmp_path: Path) -> None:
    consumer = tmp_path / "c"
    _make_consumer(consumer, scaffold_all=False)
    scan_fleet([consumer], Registry(MODULE_SOURCE_ROOT))
    # scanning never materializes files
    assert not (consumer / "ruff.toml").exists()
