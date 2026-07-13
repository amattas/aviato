"""Guard: every § requirements citation in engine code resolves through the docs index.

The 2026-07-11 docs restructure split REQUIREMENTS.md into docs/requirements/**
with § numbering preserved verbatim. docs/requirements/README.md carries the
§ -> file index. Every §N[.N] cited in aviato/**/*.py must resolve
(longest-prefix) to an indexed file that still contains the cited number.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "requirements" / "README.md"
MATRIX = ROOT / "docs" / "requirements" / "traceability.md"
CODE_ROOT = ROOT / "aviato"

LOAD_BEARING_README_TERMS = {
    "--write",
    "--migrate-profile",
    "--allow-dirty",
    "--var",
    "--public",
    "--override-version-pin",
    "--fix",
    "--audit",
    "--delete-files",
    "--rebaseline-seeds",
    "serve-pages",
}

STALE_NORMATIVE_TEXT = {
    "Advance floating major reference UNCONDITIONALLY",
    "Deploy from a branch → gh-pages",
    "no grep mirror",
}

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


def test_readme_documents_load_bearing_operator_flags() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = sorted(term for term in LOAD_BEARING_README_TERMS if term not in readme)
    assert not missing, f"README omits load-bearing operator terms: {missing}"


def test_readme_documents_exact_external_control_verification() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required = {
        "repos/amattas/aviato/rulesets/${id}",
        "Required reviewers are an operator prerequisite",
        "job ID `deploy`",
        "display name `Deploy GitHub Pages`",
        "`actions/deploy-pages`",
    }
    missing = sorted(term for term in required if term not in readme)
    assert not missing, f"README omits exact external-control verification: {missing}"
    assert "an empty list is rejected at deploy time" not in readme


def test_current_requirements_do_not_retain_stale_normative_text() -> None:
    current = [
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "docs" / "architecture" / "infrastructure.md",
        ROOT / "docs" / "architecture" / "validation.md",
        *sorted((ROOT / "docs" / "requirements").rglob("*.md")),
        *sorted((ROOT / "docs" / "specifications").rglob("*.md")),
    ]
    hits = [
        f"{path.relative_to(ROOT)}: {term}"
        for path in current
        for term in STALE_NORMATIVE_TEXT
        if term in path.read_text(encoding="utf-8")
    ]
    assert not hits, "stale normative text remains:\n" + "\n".join(hits)


def test_backlogs_contain_only_open_work_and_settled_decisions() -> None:
    for path in sorted((ROOT / "docs/requirements").rglob("backlog.md")):
        text = path.read_text(encoding="utf-8")
        headings = set(re.findall(r"^## (.+)$", text, re.MULTILINE))
        assert "Open" in headings, path
        assert "Settled — do not reopen" in headings, path
        assert not {heading for heading in headings if "Resolved" in heading or "Completed" in heading}, path


def test_completed_superpowers_artifacts_are_pruned_but_active_plan_remains() -> None:
    completed = (
        "plans/2026-05-21-agnostic-core-engine.md",
        "plans/2026-05-29-actionpins-zizmor-migration.md",
        "plans/2026-07-11-docs-restructure.md",
        "plans/2026-07-11-zensical-docs.md",
        "plans/2026-07-12-starter-documentation-governance.md",
        "specs/2026-05-29-actionpins-zizmor-migration-design.md",
        "specs/2026-07-11-docs-restructure-design.md",
        "specs/2026-07-11-zensical-docs-design.md",
        "specs/2026-07-12-starter-documentation-governance-design.md",
    )
    root = ROOT / "docs/superpowers"
    assert [path for path in completed if (root / path).exists()] == []
    assert (root / "plans/2026-07-12-repository-integrity-release-hardening.md").is_file()


def test_active_hardening_plan_matches_current_rollout_state() -> None:
    path = ROOT / "docs/superpowers/plans/2026-07-12-repository-integrity-release-hardening.md"
    text = path.read_text(encoding="utf-8")
    required = {
        "PR #60",
        "PR #59",
        "release PR #42",
        "temporary admin bypass",
        "docs: false",
        "SEC-007",
        "Dependabot",
        "TestPyPI",
    }
    forbidden = {
        ".github/aviato.seed.json",
        ".github/workflows/aviato-docs.yml",
        "website/zensical.toml",
        "website/requirements.txt",
        "docs/requirements/modules/onboarding/flow.md",
        "docs/requirements/modules/security/scanning.md",
    }
    assert sorted(term for term in required if term not in text) == []
    assert sorted(term for term in forbidden if term in text) == []


SPECIFICATION_MOVES = (
    ("6", "core/consumer-contract.md", "core/consumer-contract.md"),
    ("5.2", "modules/onboarding/flow.md", "modules/onboarding/flow.md"),
    ("5.10", "modules/onboarding/bootstrap.md", "modules/onboarding/bootstrap.md"),
    ("5.3", "modules/scaffolding/sync.md", "modules/scaffolding/sync.md"),
    ("5.5", "modules/drift/file-drift.md", "modules/drift/file-drift.md"),
    ("5.6", "modules/drift/settings-drift.md", "modules/drift/settings-drift.md"),
    ("5.4", "modules/fleet/diagnosis.md", "modules/fleet/diagnosis.md"),
    ("5.11", "modules/fleet/scan.md", "modules/fleet/scan.md"),
    ("5.7", "modules/reconcile/flow.md", "modules/reconcile/flow.md"),
    ("5.8", "modules/reconcile/consent.md", "modules/reconcile/consent.md"),
    ("5.9", "modules/versioning/release.md", "modules/versioning/release.md"),
    ("5.12", "modules/versioning/repin.md", "modules/versioning/repin.md"),
    ("5.13", "modules/offboarding/flow.md", "modules/offboarding/flow.md"),
    ("5.14", "modules/security/scanning.md", "modules/security/scanning.md"),
    ("11.3", "modules/security/supply-chain.md", "modules/security/supply-chain.md"),
    ("12.1", "modules/languages/python/requirements.md", "modules/languages/python/requirements.md"),
    ("12.2", "modules/languages/node/requirements.md", "modules/languages/node/requirements.md"),
    ("12.3", "modules/languages/swift/requirements.md", "modules/languages/swift/requirements.md"),
    ("13.1", "modules/deployment/pypi/requirements.md", "modules/deployment/pypi/requirements.md"),
    ("13.2", "modules/deployment/ghcr/requirements.md", "modules/deployment/ghcr/requirements.md"),
    ("13.3", "modules/deployment/docs-site/requirements.md", "modules/deployment/docs-site/requirements.md"),
    ("13.4", "modules/deployment/apple/requirements.md", "modules/deployment/apple/requirements.md"),
)


@pytest.mark.parametrize(("section", "old_rel", "new_rel"), SPECIFICATION_MOVES)
def test_behavioral_contracts_live_under_specifications(section: str, old_rel: str, new_rel: str) -> None:
    old_path = ROOT / "docs/requirements" / old_rel
    new_path = ROOT / "docs/specifications" / new_rel
    assert not old_path.exists(), f"§{section} remains under requirements: {old_path.relative_to(ROOT)}"
    assert new_path.is_file(), f"§{section} specification missing: {new_path.relative_to(ROOT)}"
    assert _index()[section].resolve() == new_path.resolve()


def test_specifications_index_defines_document_ownership() -> None:
    text = (ROOT / "docs/specifications/README.md").read_text(encoding="utf-8")
    required = {"precise", "testable", "Requirements", "Architecture", "Security", "§"}
    assert sorted(term for term in required if term not in text) == []


def _matrix_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| ID "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == 7, f"traceability row must have 7 fields: {line}"
        assert cells[0] not in rows, f"duplicate traceability ID: {cells[0]}"
        rows[cells[0]] = cells
    return rows


def _headed_ids(path: Path, prefix: str) -> set[str]:
    pattern = re.compile(rf"^## ({re.escape(prefix)}-[0-9]{{3}})\b", re.MULTILINE)
    return set(pattern.findall(path.read_text(encoding="utf-8")))


def _stable_requirement_ids() -> set[str]:
    pattern = re.compile(r"^## (REQ-[A-Z0-9-]+)\b", re.MULTILINE)
    return {
        identifier
        for path in (ROOT / "docs/requirements").rglob("*.md")
        for identifier in pattern.findall(path.read_text(encoding="utf-8"))
    }


def test_security_records_cross_link_threats_controls_and_architecture() -> None:
    threat_model = ROOT / "docs/security/threat-model.md"
    controls = ROOT / "docs/security/controls.md"
    architecture = ROOT / "docs/architecture/security.md"
    assert threat_model.is_file()
    assert controls.is_file()
    assert architecture.is_file()
    assert _headed_ids(threat_model, "THREAT")
    assert _headed_ids(controls, "SEC")
    for path in (threat_model, controls, architecture):
        text = path.read_text(encoding="utf-8")
        assert "THREAT-" in text, path
        assert "SEC-" in text, path
        assert "traceability.md" in text, path


def test_traceability_has_exactly_one_row_per_requirement_threat_and_control() -> None:
    rows = _matrix_rows()
    expected = {f"§{section}" for section in _index()}
    expected |= _stable_requirement_ids()
    expected |= _headed_ids(ROOT / "docs/security/threat-model.md", "THREAT")
    expected |= _headed_ids(ROOT / "docs/security/controls.md", "SEC")
    assert set(rows) == expected


def test_traceability_states_are_canonical_and_evidence_gated() -> None:
    allowed = {"proposed", "accepted", "implemented", "verified", "blocked", "retired"}
    for identifier, cells in _matrix_rows().items():
        state = cells[2]
        assert state in allowed, f"{identifier}: invalid state {state!r}"
        if state in {"implemented", "verified"}:
            assert cells[4] not in {"", "—"}, f"{identifier}: {state} without implementation evidence"
        if state == "verified":
            assert cells[5] not in {"", "—"}, f"{identifier}: verified without verification evidence"


def test_traceability_local_links_resolve() -> None:
    link = re.compile(r"\[[^]]+\]\(([^)]+)\)")
    for identifier, cells in _matrix_rows().items():
        for target in link.findall(" ".join(cells[1:])):
            if "://" in target:
                continue
            relative = target.split("#", 1)[0]
            assert relative, f"{identifier}: anchor-only evidence is not precise enough"
            assert (MATRIX.parent / relative).resolve().exists(), f"{identifier}: broken link {target}"


@pytest.mark.parametrize(
    ("identifier", "required_tokens"),
    (
        ("§2.1", ("aviato/core/composition.py", "tests/core/test_composition.py")),
        ("§2.3", (".github/workflows/reusable-release.yml", "tests/test_pipeline_privileges.py")),
        ("§2.7", ("aviato/core/consent.py", "tests/core/test_consent.py")),
        ("§2.8", ("aviato/core/reconcile_flow.py", "tests/core/test_reconcile_flow.py")),
        ("§2.11", ("aviato/core/provision.py", "tests/core/test_provision.py")),
        ("§2.13", (".github/workflows/reusable-security-baseline.yml", "tests/test_workflow_guards.py")),
        ("§2.14", ("aviato/core/ports.py", "tests/core/test_ports.py")),
        ("SEC-003", ("actions/runs/29219938630",)),
        ("SEC-010", ("pull/59",)),
    ),
)
def test_high_risk_traceability_rows_use_precise_evidence(identifier: str, required_tokens: tuple[str, ...]) -> None:
    row = " ".join(_matrix_rows()[identifier])
    assert [token for token in required_tokens if token not in row] == []


@pytest.mark.parametrize(
    "identifier",
    (
        "§2.2",
        "§3",
        "§4",
        "§5",
        "§6",
        "§7",
        "§8",
        "§10",
        "§11",
        "§12",
        "§13",
        "§14",
        "§15",
        "§18",
    ),
)
def test_normative_or_aggregate_traceability_rows_do_not_overclaim_verification(identifier: str) -> None:
    cells = _matrix_rows()[identifier]
    assert cells[2] == "accepted"
    assert cells[4] == "—"
    assert cells[5] == "—"


@pytest.mark.parametrize(
    "identifier",
    (
        "§9",
        "§11.6",
        "§13.1",
        "§13.2",
        "§13.3",
        "§13.4",
        "§13.5",
        "§16",
        "§17",
        "SEC-001",
        "SEC-005",
        "SEC-007",
        "SEC-010",
    ),
)
def test_actionable_traceability_rows_link_to_an_owning_backlog(identifier: str) -> None:
    notes = _matrix_rows()[identifier][6]
    targets = [target for target in re.findall(r"\[[^]]+\]\(([^)]+backlog\.md)\)", notes)]
    assert len(targets) == 1, f"{identifier}: expected one owning backlog link"
    backlog = (MATRIX.parent / targets[0]).resolve()
    assert identifier in backlog.read_text(encoding="utf-8"), f"{identifier}: owning backlog omits trace ID"
