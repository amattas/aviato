from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aviato.paths import REPO_ROOT
from aviato.validation import RELEASE_WORKFLOWS, validate

# pytest-of-* / aviato-* / .tmpdir*: temp litter that lands in the repo root when the
# system temp dir is unwritable (Python's tempfile falls back to cwd). Copying it would
# recurse into prior runs' nested repo copies — see also the basetemp guard in conftest.py.
_IGNORE = shutil.ignore_patterns(
    ".git",
    "_wheelout",
    "__pycache__",
    "*.egg-info",
    ".ruff_cache",
    ".pytest_cache",
    ".DS_Store",
    "pytest-of-*",
    ".tmpdir*",
    "aviato-onboard-*",
    "aviato-offboard-*",
    "aviato-scanfix-*",
    # The Library's own docs site (self-docs): node_modules is huge and contains a
    # file the sandboxed test env cannot read (*Secret* deny rule) — and validate()
    # never looks inside it.
    "node_modules",
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
        "TAG_PATTERN: '^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(-(alpha|beta)[0-9]+)?$'",
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


def test_unreconcilable_baseline_settings_key_is_detected(repo_copy: Path) -> None:
    # §5.1 (M-1): a baseline default-branch key the apply path can't write would be phantom drift
    # — `validate` must flag a Library-side typo/unmodeled key loudly.
    baseline = repo_copy / "aviato" / "library" / "bundles" / "settings" / "baseline.yaml"
    text = baseline.read_text(encoding="utf-8")
    drifted = text.replace("block_force_push: true", "block_force_push: true\n    block_force_pushh: true")
    assert drifted != text, "fixture did not contain the expected key literal"
    baseline.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("unreconcilable" in e and "block_force_pushh" in e for e in errors)


def test_template_scaffold_parity_drift_is_detected(repo_copy: Path) -> None:
    templates = sorted((repo_copy / "templates").glob("profile-*.yml"))
    assert templates, "expected committed template examples"
    target = templates[0]
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift injected\n", encoding="utf-8")
    errors = validate(repo_copy)
    assert any("does not match" in e or "Regenerate" in e or "parity" in e.lower() for e in errors)


def test_template_main_ref_is_detected(repo_copy: Path) -> None:
    # Documentation examples must not advertise a mutable production ref. They render
    # with EXAMPLE_PIN; a regression to @main is a validation error, not just a docs nit.
    target = repo_copy / "templates" / "profile-python-library.yml"
    text = target.read_text(encoding="utf-8")
    drifted = text.replace("@EXAMPLE_PIN", "@main", 1)
    assert drifted != text, "fixture did not contain an EXAMPLE_PIN reusable-workflow ref"
    target.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("advertises @main" in e for e in errors)


def test_library_bootstrap_profile_mismatch_is_detected(repo_copy: Path) -> None:
    # The Library declaration must match the artifacts it actually self-applies. If it
    # points back at the public python-library scaffold, validation must catch the extra
    # expected managed files instead of checking only the two workflow callers.
    decl = repo_copy / ".github" / "aviato.yaml"
    text = decl.read_text(encoding="utf-8").replace("profile: aviato-library", "profile: python-library")
    text = text.replace("variables:\n", "variables:\n  distribution-name: aviato\n")
    decl.write_text(text, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("missing Library bootstrap managed artifact" in e for e in errors)


def test_static_ruleset_pattern_drift_is_detected(repo_copy: Path) -> None:
    # The static ruleset template literal is render-injected from policy, but it must still
    # be drift-checked against policy — otherwise editing it (e.g. re-adding a leading v)
    # leaves validation green. Regression guard for the previously-tautological check.
    import json

    f = repo_copy / "aviato" / "library" / "rulesets" / "release-tag-format.json"
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


def test_baseline_required_reviews_deletion_is_detected(repo_copy: Path) -> None:
    # R3-11: removing the baseline approval setting entirely must FAIL validation (it previously
    # returned clean when the key was absent).
    import yaml as _yaml

    f = repo_copy / "aviato" / "library" / "bundles" / "settings" / "baseline.yaml"
    doc = _yaml.safe_load(f.read_text())
    doc["settings"]["default_branch"].pop("required_reviews", None)
    f.write_text(_yaml.safe_dump(doc), encoding="utf-8")
    errors = validate(repo_copy)
    assert any("required_reviews" in e and "missing" in e for e in errors)


def test_branch_ruleset_approval_literal_drift_is_detected(repo_copy: Path) -> None:
    # review #24: the branch ruleset's required_approving_review_count is render-injected from
    # policy, but the static literal must ALSO be drift-checked (the tag-pattern check was, the
    # branch approval one was not). Mutating it must turn validation red.
    import json

    f = repo_copy / "aviato" / "library" / "rulesets" / "protect-default-branch.json"
    payload = json.loads(f.read_text(encoding="utf-8"))
    mutated = False
    for rule in payload["rules"]:
        if rule.get("type") == "pull_request":
            rule["parameters"]["required_approving_review_count"] = 99
            mutated = True
    assert mutated, "fixture did not contain a pull_request rule"
    f.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    errors = validate(repo_copy)
    assert any("required_approving_review_count" in e and "policy.yml" in e for e in errors)


@pytest.mark.parametrize(
    "rel_path",
    [
        ".github/workflows/reusable-docker-ghcr.yml",
        "starter/docs-site/docs.yml",  # the starter kit's hand-copied comparator joins the battery
    ],
)
def test_monotonic_alias_inline_drift_is_detected(repo_copy: Path, rel_path: str) -> None:
    # The deploy workflows embed a hand-copied `highest.py` that must agree with core's
    # is_highest (§8.14/§13.2). Flip its prerelease rank so a final release no longer outranks
    # its beta/alpha — validation must catch the divergence (else an alias could move backward).
    f = repo_copy / rel_path
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


def test_checkout_by_repository_name_in_release_workflow_is_detected(repo_copy: Path) -> None:
    # §11.3: a release workflow that checks out Aviato by repository name can drift from
    # the pinned workflow ref — the contract check is text-operative, so any occurrence
    # of the slug-qualified checkout must flag.
    wf = repo_copy / RELEASE_WORKFLOWS[0]
    with wf.open("a", encoding="utf-8") as handle:
        handle.write("\n# drift fixture:\n#          repository: amattas/aviato\n")
    errors = validate(repo_copy)
    assert any("checks out Aviato by repository name" in e for e in errors)


def test_missing_required_file_is_detected(repo_copy: Path) -> None:
    (repo_copy / "templates" / "consumer-automation.yml").unlink()
    errors = validate(repo_copy)
    assert any(e == "missing required file: templates/consumer-automation.yml" for e in errors)


def test_stale_library_bootstrap_artifact_is_detected(repo_copy: Path) -> None:
    # §5.10: a hand-edited bootstrap-managed artifact must be flagged as stale.
    wf = repo_copy / ".github" / "workflows" / "aviato-ci.yml"
    wf.write_text(wf.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    errors = validate(repo_copy)
    assert any(".github/workflows/aviato-ci.yml is stale" in e and "Library bootstrap" in e for e in errors)


def test_released_aviato_ref_in_bootstrap_artifact_is_detected(repo_copy: Path) -> None:
    # §5.10: the Library's own callers must use local workflow refs, never a released
    # amattas/aviato/... ref (a released self-reference would deadlock bootstrap).
    wf = repo_copy / ".github" / "workflows" / "aviato-ci.yml"
    text = wf.read_text(encoding="utf-8")
    drifted = text.replace(
        "uses: ./.github/workflows/reusable-python-ci.yml",
        "uses: amattas/aviato/.github/workflows/reusable-python-ci.yml@1.2.3",
    )
    assert drifted != text, "fixture did not contain the expected local workflow ref"
    wf.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("released Aviato ref in bootstrap" in e for e in errors)


def test_scaffold_reference_to_missing_reusable_workflow_is_detected(repo_copy: Path) -> None:
    # A scaffold caller body referencing a reusable workflow that doesn't ship would give
    # every consumer a broken pipeline — the rendered-scaffold check must flag it.
    body = repo_copy / "aviato" / "library" / "scaffold" / "files" / "wf-python-library.yml"
    text = body.read_text(encoding="utf-8")
    drifted = text.replace("reusable-python-ci.yml", "reusable-missing-ci.yml")
    assert drifted != text, "fixture did not contain the expected reusable workflow reference"
    body.write_text(drifted, encoding="utf-8")
    errors = validate(repo_copy)
    assert any("references missing reusable workflow reusable-missing-ci.yml" in e for e in errors)


def test_docs_caller_grep_pattern_drift_is_detected(repo_copy: Path) -> None:
    # finding 39 — pattern-agnostic: reads the policy literal from the copy at test
    # time, so a future policy change does not rewrite this fixture.
    import yaml

    pattern = yaml.safe_load((repo_copy / "aviato/library/policy.yml").read_text(encoding="utf-8"))["release"][
        "tag_pattern"
    ]
    body = repo_copy / "aviato/library/scaffold/files/wf-docs-python-library.yml"
    text = body.read_text(encoding="utf-8")
    drifted = text.replace(f"grep -E '{pattern}'", "grep -E '^.*$'")
    assert drifted != text, "fixture did not contain the policy grep literal"
    body.write_text(drifted, encoding="utf-8")
    assert any("finding 39" in e for e in validate(repo_copy))


def test_docs_caller_workflow_run_name_drift_is_detected(repo_copy: Path) -> None:
    # finding 40: a renamed CI caller display name must be flagged — workflow_run
    # matches by name, so the docs deploy would otherwise just never fire again.
    ci = repo_copy / "aviato/library/scaffold/files/wf-python-library.yml"
    text = ci.read_text(encoding="utf-8")
    drifted = text.replace("name: Aviato Python Library\n", "name: Renamed Python Library\n")
    assert drifted != text, "fixture did not contain the expected display name"
    ci.write_text(drifted, encoding="utf-8")
    assert any("finding 40" in e for e in validate(repo_copy))


def test_library_slug_copy_drift_is_detected(repo_copy: Path) -> None:
    # finding 41: a desynced Library-slug copy (here: the zizmor ref-pin exemption)
    # must be flagged so a rename/transfer moves every site together.
    z = repo_copy / "aviato/library/zizmor.yml"
    text = z.read_text(encoding="utf-8")
    drifted = text.replace("amattas/aviato/*: ref-pin", "someone-else/aviato/*: ref-pin")
    assert drifted != text, "fixture did not contain the zizmor slug exemption"
    z.write_text(drifted, encoding="utf-8")
    assert any("finding 41" in e for e in validate(repo_copy))


def test_scaffold_cron_drift_is_detected(repo_copy: Path) -> None:
    # finding 43: hand-duplicated CI schedules must stay in lockstep across callers.
    body = repo_copy / "aviato/library/scaffold/files/wf-python-service.yml"
    text = body.read_text(encoding="utf-8")
    drifted = text.replace('cron: "23 5 * * 1"', 'cron: "0 0 * * 0"')
    assert drifted != text, "fixture did not contain the shared CI cron"
    body.write_text(drifted, encoding="utf-8")
    assert any("finding 43" in e for e in validate(repo_copy))


def test_docs_toolchain_pin_drift_is_flagged(repo_copy: Path) -> None:
    # Change the zensical pin in ONE of the three docs requirements sources and
    # assert validate() reports the drift (finding 43 mechanism).
    target = repo_copy / "starter" / "docs-site" / "requirements.txt"
    text = target.read_text()
    drifted = text.replace("zensical==0.0.50", "zensical==0.0.49")
    assert drifted != text, "fixture did not contain the expected zensical pin"
    target.write_text(drifted)
    errors = validate(repo_copy)
    assert any("docs toolchain pins differ" in e for e in errors), errors
