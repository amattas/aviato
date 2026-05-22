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
