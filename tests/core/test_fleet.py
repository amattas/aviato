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
        # Scaffold with the same pin the declaration records, so the embedded
        # workflow refs match what fleet expects (parity, §5.11).
        items = materialize_items(reg, "python-library", variables={}, pin="v1")
        scaffold(root, items, profile="python-library", version="v1")


def test_scan_no_false_drift_for_javascript_consumer(tmp_path: Path) -> None:
    # §5.11 parity: a JS consumer scaffolded without tsconfig must read clean, not
    # show false drift from fleet resolving without the variant.
    root = tmp_path / "js"
    github = root / ".github"
    github.mkdir(parents=True)
    (github / "aviato.yaml").write_text(
        "profile: node-service\nversion: v1\nvariables:\n  language-variant: javascript\n  project-name: x\n",
        encoding="utf-8",
    )
    reg = Registry(MODULE_SOURCE_ROOT)
    variables = {"language-variant": "javascript", "project-name": "x"}
    items = materialize_items(reg, "node-service", variables, pin="v1")
    scaffold(root, items, profile="node-service", version="v1")
    assert not (root / "tsconfig.json").exists()  # JS omits tsconfig

    scan = scan_fleet([root], Registry(MODULE_SOURCE_ROOT))[0]
    assert all(status == "clean" for status in scan.statuses.values()), scan.statuses


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


def test_scan_skips_archived_repo_unless_included(tmp_path: Path) -> None:
    # §5.11: archived repos are skipped by default and only diagnosed with --include-archived.
    consumer = tmp_path / "c"
    _make_consumer(consumer, scaffold_all=True)

    archived = scan_fleet([consumer], Registry(MODULE_SOURCE_ROOT), archived_probe=lambda root: True)
    assert archived[0].skipped_archived is True
    assert archived[0].statuses == {}  # not diagnosed

    included = scan_fleet(
        [consumer], Registry(MODULE_SOURCE_ROOT), include_archived=True, archived_probe=lambda root: True
    )
    assert included[0].skipped_archived is False
    assert included[0].statuses  # diagnosed normally


def test_scan_unknown_archived_state_is_not_skipped(tmp_path: Path) -> None:
    # §5.11 fail-safe: an ambiguous archived probe (None) must NOT silently drop the repo from
    # the operator's read-only scan — it is diagnosed as usual.
    consumer = tmp_path / "c"
    _make_consumer(consumer, scaffold_all=True)
    scans = scan_fleet([consumer], Registry(MODULE_SOURCE_ROOT), archived_probe=lambda root: None)
    assert scans[0].skipped_archived is False
    assert scans[0].statuses
