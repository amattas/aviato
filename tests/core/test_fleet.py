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
    (github / "aviato.yaml").write_text(
        "profile: python-library\nversion: v1\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    if scaffold_all:
        reg = Registry(MODULE_SOURCE_ROOT)
        # Scaffold with the same pin the declaration records, so the embedded
        # workflow refs match what fleet expects (parity, §5.11).
        items = materialize_items(
            reg,
            "python-library",
            variables={"distribution-name": "acme", "import-name": "acme"},
            pin="v1",
        )
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


def test_scan_reports_malformed_declaration_as_error_not_crash(tmp_path: Path) -> None:
    # R1-1/§5.11: a repo with corrupt YAML must be reported as that repo's error, never crash the
    # whole fleet scan. The good repo alongside it must still be scanned.
    bad = tmp_path / "bad"
    (bad / ".github").mkdir(parents=True)
    (bad / ".github" / "aviato.yaml").write_text("profile: p\nversion: '1'\nvariables: {a: [x\n", encoding="utf-8")
    good = tmp_path / "good"
    good.mkdir()  # no declaration → its own benign error row
    scans = scan_fleet([bad, good], Registry(MODULE_SOURCE_ROOT))
    assert len(scans) == 2
    assert scans[0].error is not None  # malformed YAML reported, not raised


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


def test_scan_degrades_on_non_utf8_declaration_and_dir_at_managed_path(tmp_path: Path) -> None:
    # R5-5-FLEETDEGRADE/§5.11: a consumer with a non-UTF-8 `aviato.yaml`, or a DIRECTORY at a
    # managed output path, must each be reported as that repo's error/drift — never abort the whole
    # sweep. (These bypass the AviatoError-only guard unless load_declaration catches UnicodeDecode
    # and diagnose catches OSError — R5-4-DECL / R5-3-DIAG-OS.)
    bad_enc = tmp_path / "badenc"
    (bad_enc / ".github").mkdir(parents=True)
    (bad_enc / ".github" / "aviato.yaml").write_bytes(b"profile: python-library\nversion: \xff\xfe v1\n")

    dir_at_path = tmp_path / "dirpath"
    _make_consumer(dir_at_path, scaffold_all=True)
    # Replace a managed file with a directory at its path.
    managed = dir_at_path / "ruff.toml"
    if managed.exists():
        managed.unlink()
    managed.mkdir()

    good = tmp_path / "good2"
    _make_consumer(good, scaffold_all=True)

    scans = scan_fleet([bad_enc, dir_at_path, good], Registry(MODULE_SOURCE_ROOT))
    assert len(scans) == 3  # nothing aborted the sweep
    assert scans[0].error is not None  # non-UTF-8 declaration → that repo's error row
    # dir-at-managed-path: diagnosed (no crash); the directory path reads as dirty-drift.
    assert scans[1].error is None
    assert scans[1].statuses.get("ruff.toml") == "dirty-drift"
    # the good repo is still fully diagnosed.
    assert scans[2].error is None
