from __future__ import annotations

from pathlib import Path

from aviato.core.selfcheck import (
    core_import_violations,
    denylist_violations,
    load_denylist,
)
from aviato.paths import DENYLIST_FILE


def test_denylist_is_the_maintained_list() -> None:
    denylist = load_denylist(DENYLIST_FILE)
    assert "ruff" in denylist
    assert "docusaurus" in denylist
    assert "app store" in denylist
    # Consumer-target format/language identifiers that must never re-enter core
    # (version-source rewriters and the typecheck-variant rule live in plug-ins).
    for token in ("javascript", "typescript", "package.json", "pbxproj", "plist", "pyproject"):
        assert token in denylist
    # Container/GHCR deploy-mechanism identifiers: the §11.3 action-pin logic that knows
    # `docker run` lives in the plug-in tree, so core must never name these (§9b).
    assert "docker" in denylist
    assert "container" in denylist
    # Day-zero contained advisory-model provider (D3/D4): core defines only the neutral Advisor
    # port; the concrete binding names the provider, so core must never learn these words.
    assert "azure" in denylist
    assert "openai" in denylist


def test_unparseable_core_file_is_flagged_not_silently_skipped(tmp_path: Path) -> None:
    # A core source file that fails to parse must NOT silently pass the §9b import-edge scan
    # — that would let validate() falsely report clean. Flag it as a violation instead.
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "broken.py").write_text("def f(:\n", encoding="utf-8")
    assert core_import_violations(fake_core) != []


def test_core_does_not_name_the_python_project_manifest() -> None:
    # §9b: the Python project manifest name (pyproject) must not be hardcoded in core;
    # detection of the Library is structural, not by a language-specific filename.
    assert denylist_violations(denylist={"pyproject"}) == []


def test_core_has_no_import_edge_into_plugin_tree() -> None:
    assert core_import_violations() == []


def test_core_contains_no_denylisted_identifier() -> None:
    assert denylist_violations() == []


def test_import_edge_detected_in_synthetic_core(tmp_path: Path) -> None:
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "bad.py").write_text("from aviato.plugins import comment_syntax\n")
    assert core_import_violations(fake_core) != []


def test_denylisted_token_detected_in_synthetic_core(tmp_path: Path) -> None:
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "bad.py").write_text("ENGINE = 'docusaurus'\n")
    assert denylist_violations(fake_core, {"docusaurus"}) != []


def test_core_may_not_name_zensical(tmp_path: Path) -> None:
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "bad.py").write_text("ENGINE = 'zensical'\n")
    assert denylist_violations(fake_core, {"zensical"}) != []
    denylist = load_denylist(DENYLIST_FILE)
    assert "zensical" in denylist


def test_multiword_denylist_token_matches_any_whitespace(tmp_path: Path) -> None:
    # A multi-word token must match across any whitespace run, so incidental spacing/newlines
    # cannot evade it (a literal-space pattern would only match a single ASCII space).
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "single.py").write_text("X = 'app store'\n")
    (fake_core / "double.py").write_text("X = 'app  store'\n")
    (fake_core / "newline.py").write_text("X = '''app\nstore'''\n")
    assert denylist_violations(fake_core, {"app store"}) != []
    for name in ("single.py", "double.py", "newline.py"):
        assert denylist_violations(tmp_path / "core", {"app store"}), name
    # A genuinely unrelated word still does not trip (word boundaries preserved).
    other = tmp_path / "other"
    other.mkdir()
    (other / "ok.py").write_text("X = 'appstore_helper'\n")
    assert denylist_violations(other, {"app store"}) == []


def test_multiword_denylist_token_matches_hyphen_and_concatenated(tmp_path: Path) -> None:
    # R9-20: a two-word token must also catch the hyphenated, underscored, and concatenated forms of
    # the same identifier — the exact day-zero deployment-environment spellings that a `\s+`-only
    # join missed and that let a concrete env name slip into the agnostic core.
    core = tmp_path / "core"
    core.mkdir()
    (core / "hyphen.py").write_text("env = 'app-store-connect'\n")
    (core / "concat.py").write_text("ENV = 'APPSTORE'\n")
    assert denylist_violations(core, {"app store"}) != []
    for name in ("hyphen.py", "concat.py"):
        assert any(name in v for v in denylist_violations(core, {"app store"})), name


def test_dynamic_import_edge_detected_in_synthetic_core(tmp_path: Path) -> None:
    # §9b: the check flags ANY dynamic import in core, not just one whose argument literally
    # spells the plug-in tree. That breadth is the point — core has no legitimate dynamic-import
    # need, so a string-assembled `import_module('aviato.'+'plugins')` (the evasion a line-regex
    # would miss) cannot hide behind an opaque argument. Assert BOTH: the plugin-assembly case
    # AND a benign-looking target are flagged (the latter pins the "any dynamic import" policy,
    # so the test can't silently pass on argument-blindness alone).
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "sneaky.py").write_text("import importlib\nmod = importlib.import_module('aviato.' + 'plugins')\n")
    assert core_import_violations(fake_core) != []
    (fake_core / "sneaky.py").unlink()
    (fake_core / "benign.py").write_text("import importlib\nmod = importlib.import_module('os')\n")
    assert core_import_violations(fake_core) != []


def test_relative_import_edge_detected_in_synthetic_core(tmp_path: Path) -> None:
    # A relative `from ..plugins import x` reaches the same plug-in tree and must be caught.
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "rel.py").write_text("from ..plugins import comment_syntax\n")
    assert core_import_violations(fake_core) != []


def test_relative_import_edge_from_core_subpackage_is_detected(tmp_path: Path) -> None:
    # §9b soundness: a file in a nested core subpackage must not escape the scan. From
    # aviato.core.sub, `from ...plugins import x` (level 3) reaches aviato.plugins. The
    # resolver must derive the package from the file's path, not assume core is flat —
    # otherwise this edge resolves to a bare "plugins" and slips through.
    fake_core = tmp_path / "core"
    sub = fake_core / "sub"
    sub.mkdir(parents=True)
    (sub / "deep.py").write_text("from ...plugins import comment_syntax\n")
    assert core_import_violations(fake_core) != []


def test_relative_sibling_import_in_subpackage_does_not_trip(tmp_path: Path) -> None:
    # A legitimate intra-subpackage `from . import sibling` must NOT be flagged.
    fake_core = tmp_path / "core"
    sub = fake_core / "sub"
    sub.mkdir(parents=True)
    (sub / "ok.py").write_text("from . import sibling\n")
    assert core_import_violations(fake_core) == []


def test_comment_mentioning_plugin_tree_does_not_trip(tmp_path: Path) -> None:
    # A prose mention of the plug-in package in a comment is not an import edge.
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "ok.py").write_text("# see aviato.plugins.comment_syntax for the mapping\nX = 1\n")
    assert core_import_violations(fake_core) == []


def test_substring_does_not_falsely_trip(tmp_path: Path) -> None:
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    # "nodes" contains "node" but is a different word; boundaries must not trip it
    (fake_core / "ok.py").write_text("graph_nodes = []\n")
    assert denylist_violations(fake_core, {"node"}) == []


def test_denylist_violations_are_reported_per_file(tmp_path: Path) -> None:
    # R5-9: the suite must lock PER-FILE granularity, not just "some violation exists" — a regression
    # that scanned files in one merged blob would still report a violation but lose which shape
    # carries it. Two synthetic core files (one offending, one clean): the offender's name appears,
    # the clean file's never does.
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "offends.py").write_text("X = 'docusaurus'\n")
    (fake_core / "clean.py").write_text("X = 'unrelated'\n")
    violations = denylist_violations(fake_core, {"docusaurus"})
    assert any(v.startswith("offends.py:") for v in violations)
    assert not any("clean.py" in v for v in violations)
