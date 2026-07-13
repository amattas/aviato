from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "starter"
SKILLS = ("docs-structure", "traceability", "docs-reconciliation", "test-consolidation")
START = "<!-- aviato:documentation-governance:start -->"
END = "<!-- aviato:documentation-governance:end -->"


def _managed_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.count(START) == text.count(END) == 1
    return START + text.split(START, 1)[1].split(END, 1)[0] + END


def test_starter_governance_assets_exist() -> None:
    expected = [STARTER / name for name in ("CLAUDE.md", "AGENTS.md")]
    expected += [STARTER / "skills" / name / "SKILL.md" for name in SKILLS]
    expected += [STARTER / "docs/requirements/traceability.md"]
    assert [path.relative_to(ROOT) for path in expected if not path.is_file()] == []


def test_agent_templates_share_the_exact_managed_block() -> None:
    assert _managed_block(STARTER / "CLAUDE.md") == _managed_block(STARTER / "AGENTS.md")


def test_managed_block_names_skills_completion_and_cost_rules() -> None:
    block = _managed_block(STARTER / "AGENTS.md")
    required = {
        *SKILLS,
        "docs/requirements/traceability.md",
        "completed work",
        "parameterized",
        "CI",
        "rework",
    }
    assert sorted(term for term in required if term not in block) == []


def test_traceability_template_has_canonical_schema_and_states() -> None:
    text = (STARTER / "docs/requirements/traceability.md").read_text(encoding="utf-8")
    for column in (
        "ID",
        "Source",
        "State",
        "Specification",
        "Implementation evidence",
        "Verification evidence",
        "Notes",
    ):
        assert f"| {column} " in text
    for state in ("proposed", "accepted", "implemented", "verified", "blocked", "retired"):
        assert f"`{state}`" in text
