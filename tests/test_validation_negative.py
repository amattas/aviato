from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aviato.paths import REPO_ROOT
from aviato.validation import RELEASE_WORKFLOWS, validate

_IGNORE = shutil.ignore_patterns(
    ".git", "_wheelout", "__pycache__", "*.egg-info", ".ruff_cache", ".pytest_cache", ".DS_Store"
)


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "repo"
    shutil.copytree(REPO_ROOT, dst, ignore=_IGNORE)
    return dst


def test_clean_copy_validates(repo_copy: Path) -> None:
    # Baseline: an untouched copy validates, so the negative tests below isolate the drift.
    assert validate(repo_copy) == []


def test_tag_pattern_drift_in_release_workflow_is_detected(repo_copy: Path) -> None:
    wf = repo_copy / RELEASE_WORKFLOWS[0]
    text = wf.read_text(encoding="utf-8")
    drifted = text.replace(
        "TAG_PATTERN: '^[0-9]+\\.[0-9]+\\.[0-9]+(-(alpha|beta)[0-9]+)?$'",
        "TAG_PATTERN: '^[0-9]+\\.[0-9]+$'",
    )
    assert drifted != text, "fixture did not contain the expected TAG_PATTERN literal"
    wf.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("TAG_PATTERN" in e or "release tag pattern" in e for e in errors)


def test_legacy_release_branch_trigger_is_detected(repo_copy: Path) -> None:
    wf = repo_copy / RELEASE_WORKFLOWS[0]
    wf.write_text(wf.read_text(encoding="utf-8") + "\n# on: push: branches: [release/*]\n", encoding="utf-8")
    errors = validate(repo_copy)
    assert any("legacy release branch" in e for e in errors)


def test_release_workflow_missing_tag_ref_guard_is_detected(repo_copy: Path) -> None:
    # The operative guard is the shell comparison that gates publishing on a tag ref;
    # a workflow that drops it must be flagged (a bare GITHUB_REF_TYPE mention in a
    # comment is not enough).
    wf = repo_copy / RELEASE_WORKFLOWS[0]
    text = wf.read_text(encoding="utf-8")
    stripped = text.replace('"${GITHUB_REF_TYPE}" != "tag"', '"${GITHUB_REF_TYPE}" != "branch"')
    assert stripped != text, "fixture did not contain the operative tag-ref guard"
    wf.write_text(stripped, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("tag ref" in e for e in errors)


def test_tag_format_description_drift_is_detected(repo_copy: Path) -> None:
    # The operator-facing tag-format description must match policy.yml; otherwise the
    # error message can advertise a format the pattern rejects (e.g. a leading v).
    wf = repo_copy / RELEASE_WORKFLOWS[0]
    text = wf.read_text(encoding="utf-8")
    drifted = text.replace(
        "TAG_FORMAT_DESCRIPTION: 'N.N.N, N.N.N-alphaN, or N.N.N-betaN'",
        "TAG_FORMAT_DESCRIPTION: 'vN.N.N'",
    )
    assert drifted != text, "fixture did not contain the policy tag_format_description"
    wf.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("tag_format_description" in e.lower() or "tag format description" in e.lower() for e in errors)


def test_denylisted_identifier_in_core_is_detected(repo_copy: Path) -> None:
    bad = repo_copy / "aviato" / "core" / "_injected_leak.py"
    bad.write_text("ENGINE = 'pbxproj'\n", encoding="utf-8")
    errors = validate(repo_copy)
    assert any("denylisted identifier" in e for e in errors)


def test_baseline_required_reviews_drift_is_detected(repo_copy: Path) -> None:
    # policy.yml is the single source of truth for required approvals; the desired-state
    # baseline must not silently drift from it.
    baseline = repo_copy / "aviato" / "library" / "bundles" / "settings" / "baseline.yaml"
    text = baseline.read_text(encoding="utf-8")
    drifted = text.replace("required_reviews: 1", "required_reviews: 5")
    assert drifted != text, "fixture did not contain the expected required_reviews literal"
    baseline.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("required_reviews" in e or "required approvals" in e.lower() for e in errors)


def test_template_scaffold_parity_drift_is_detected(repo_copy: Path) -> None:
    templates = sorted((repo_copy / "templates").glob("profile-*.yml"))
    assert templates, "expected committed template examples"
    target = templates[0]
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift injected\n", encoding="utf-8")
    errors = validate(repo_copy)
    assert any("does not match" in e or "Regenerate" in e or "parity" in e.lower() for e in errors)


def test_static_ruleset_pattern_drift_is_detected(repo_copy: Path) -> None:
    # The static ruleset template literal is render-injected from policy, but it must still
    # be drift-checked against policy — otherwise editing it (e.g. re-adding a leading v)
    # leaves validation green. Regression guard for the previously-tautological check.
    import json

    f = repo_copy / "rulesets" / "release-tag-format.json"
    payload = json.loads(f.read_text(encoding="utf-8"))
    mutated = False
    for rule in payload["rules"]:
        if rule.get("type") == "tag_name_pattern":
            rule["parameters"]["pattern"] = "^v[0-9]+\\.[0-9]+\\.[0-9]+$"
            mutated = True
    assert mutated, "fixture did not contain a tag_name_pattern rule"
    f.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    errors = validate(repo_copy)
    assert any("tag_name_pattern" in e and "policy.yml" in e for e in errors)


def test_monotonic_alias_inline_drift_is_detected(repo_copy: Path) -> None:
    # The deploy workflows embed a hand-copied `highest.py` that must agree with core's
    # is_highest (§8.14/§13.2). Flip its prerelease rank so a final release no longer outranks
    # its beta/alpha — validation must catch the divergence (else an alias could move backward).
    f = repo_copy / ".github" / "workflows" / "reusable-docker-ghcr.yml"
    text = f.read_text(encoding="utf-8")
    drifted = text.replace('rank = {None: 2, "beta": 1, "alpha": 0}', 'rank = {None: 0, "beta": 1, "alpha": 2}')
    assert drifted != text, "fixture did not contain the expected inline rank table"
    f.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("is_highest" in e and "drifted" in e for e in errors)


def test_monotonic_alias_inline_guard_removal_is_detected(repo_copy: Path) -> None:
    # Deleting the inline guard entirely (no `<<'PY'` heredoc) must also fail — a removed guard
    # is the most dangerous drift (the alias would move unconditionally).
    f = repo_copy / ".github" / "workflows" / "reusable-docs-pages.yml"
    text = f.read_text(encoding="utf-8")
    # Drop every heredoc line so no PY block remains.
    stripped = "\n".join(line for line in text.splitlines() if "<<'PY'" not in line and line.strip() != "PY")
    f.write_text(stripped, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("monotonic-alias guard is missing" in e for e in errors)
