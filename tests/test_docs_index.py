"""Guard: every § requirements citation in engine code resolves through the docs index.

The 2026-07-11 docs restructure split REQUIREMENTS.md into docs/requirements/**
with § numbering preserved verbatim. docs/requirements/README.md carries the
§ -> file index. Every §N[.N] cited in aviato/**/*.py must resolve
(longest-prefix) to an indexed file that still contains the cited number.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "requirements" / "README.md"
CODE_ROOT = ROOT / "aviato"

# Citations whose literal number never appeared in REQUIREMENTS.md:
# §9.2 cites item 2 of §9's list (the items are unnumbered prose in the
# source). Prefix resolution to §9 is the strongest possible check for it.
LITERAL_ABSENT_OK = {"9.2"}

REF_RE = re.compile(r"§\s*([0-9][0-9a-z.]*)")
ROW_RE = re.compile(r"^\|\s*§([0-9][0-9a-z.]*)\s*\|[^|]*\|\s*([^|]+?)\s*\|\s*$")


def _index() -> dict[str, Path]:
    rows: dict[str, Path] = {}
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        match = ROW_RE.match(line)
        if match:
            rows[match.group(1)] = INDEX.parent / match.group(2)
    return rows


def _cited() -> set[str]:
    refs: set[str] = set()
    for source in CODE_ROOT.rglob("*.py"):
        for match in REF_RE.finditer(source.read_text(encoding="utf-8")):
            refs.add(match.group(1).rstrip("."))
    return refs


def _resolve(ref: str, index: dict[str, Path]) -> Path | None:
    key = ref
    while True:
        if key in index:
            return index[key]
        if "." not in key:
            return None
        key = key.rsplit(".", 1)[0]


def test_index_rows_exist_and_contain_their_heading() -> None:
    index = _index()
    assert index, f"no § rows parsed from {INDEX}"
    for key, path in index.items():
        assert path.is_file(), f"§{key}: indexed file missing: {path}"
        heading = re.compile(rf"^#{{1,3}} {re.escape(key)}[. ]", re.MULTILINE)
        assert heading.search(path.read_text(encoding="utf-8")), f"§{key}: heading not found in {path}"


def test_every_code_citation_resolves_through_the_index() -> None:
    index = _index()
    cited = _cited()
    assert cited, "no § citations found in aviato/**/*.py"
    unresolved: list[str] = []
    literal_missing: list[str] = []
    for ref in sorted(cited):
        target = _resolve(ref, index)
        if target is None or not target.is_file():
            unresolved.append(ref)
        elif ref not in LITERAL_ABSENT_OK and ref not in target.read_text(encoding="utf-8"):
            literal_missing.append(f"§{ref} -> {target.relative_to(ROOT)}")
    assert not unresolved, f"citations with no index entry: {unresolved}"
    assert not literal_missing, f"cited numbers absent from their resolved file: {literal_missing}"
