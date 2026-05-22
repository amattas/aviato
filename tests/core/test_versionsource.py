from __future__ import annotations

import json
from pathlib import Path

import pytest

from aviato.core.errors import AviatoError
from aviato.plugins.version_formats import bump_files, bump_text


def test_bump_pyproject_version() -> None:
    text = '[project]\nname = "x"\nversion = "1.2.3"\n'
    assert 'version = "2.0.0"' in bump_text("pyproject.toml", text, "2.0.0")


def test_manifests_get_bare_semver_not_v_prefixed() -> None:
    # the v-prefixed tag must be written bare into manifests (§3.3).
    assert 'version = "1.3.0"' in bump_text("pyproject.toml", '[project]\nversion = "1.2.3"\n', "v1.3.0")
    assert json.loads(bump_text("package.json", '{"version": "0.1.0"}', "v0.2.0"))["version"] == "0.2.0"


def test_bump_swift_pbxproj_marketing_and_build() -> None:
    text = "MARKETING_VERSION = 1.0.0;\nCURRENT_PROJECT_VERSION = 1;\n"
    out = bump_text("project.pbxproj", text, "v2.1.0", build_number="42")
    assert "MARKETING_VERSION = 2.1.0;" in out
    assert "CURRENT_PROJECT_VERSION = 42;" in out


def test_bump_swift_plist() -> None:
    text = (
        "<key>CFBundleShortVersionString</key>\n<string>1.0.0</string>\n"
        "<key>CFBundleVersion</key>\n<string>1</string>\n"
    )
    out = bump_text("Info.plist", text, "v2.1.0", build_number="42")
    assert "<string>2.1.0</string>" in out
    assert "<string>42</string>" in out


def test_bump_pyproject_without_version_errors() -> None:
    with pytest.raises(AviatoError):
        bump_text("pyproject.toml", "[project]\nname = 'x'\n", "2.0.0")


def test_bump_package_json_version() -> None:
    out = bump_text("package.json", '{"name": "x", "version": "0.1.0"}', "0.2.0")
    assert json.loads(out)["version"] == "0.2.0"


def test_bump_package_json_is_surgical_and_preserves_formatting() -> None:
    # §3.3: bump the version string only — do not reserialize and churn the
    # operator-owned manifest's formatting/key order (it is seed-once, §6.3).
    text = '{\n  "name": "x",\n  "version": "0.1.0",\n  "scripts": { "build": "tsc" }\n}\n'
    out = bump_text("package.json", text, "0.2.0")
    assert out == text.replace('"0.1.0"', '"0.2.0"')


def test_bump_pyproject_only_rewrites_project_table_not_other_tables() -> None:
    # Only the [project] (or [tool.poetry]) version is the package version. A tool
    # table that also carries version = "..." MUST be left untouched — a global
    # subn would clobber every top-level version= line (§3.3).
    text = (
        '[build-system]\nrequires = ["hatchling"]\n\n'
        '[project]\nname = "x"\nversion = "1.2.3"\n\n'
        '[tool.bumpver]\nversion = "1.2.3"\n'
    )
    out = bump_text("pyproject.toml", text, "2.0.0")
    assert '[project]\nname = "x"\nversion = "2.0.0"' in out
    assert '[tool.bumpver]\nversion = "1.2.3"' in out


def test_bump_pyproject_poetry_table() -> None:
    text = '[tool.poetry]\nname = "x"\nversion = "1.2.3"\n'
    assert 'version = "2.0.0"' in bump_text("pyproject.toml", text, "2.0.0")


def test_bump_package_json_ignores_nested_version_with_same_value() -> None:
    # A nested object carrying the same version string (textually first) must NOT be
    # rewritten in place of the top-level package version (§3.3).
    text = '{\n  "dependencies": { "dep": { "version": "0.1.0" } },\n  "version": "0.1.0"\n}\n'
    out = bump_text("package.json", text, "0.2.0")
    data = json.loads(out)
    assert data["version"] == "0.2.0"
    assert data["dependencies"]["dep"]["version"] == "0.1.0"


def test_bump_package_json_without_version_errors() -> None:
    with pytest.raises(AviatoError):
        bump_text("package.json", '{"name": "x"}', "0.2.0")


def test_bump_unsupported_file_unchanged() -> None:
    assert bump_text("build.gradle", "version 1.0", "9.9.9") == "version 1.0"


def test_bump_pbxproj_idempotent_when_already_at_target() -> None:
    # Re-bumping a .pbxproj to the version it already holds is a successful no-op, not a
    # "no MARKETING_VERSION found" error: the field IS present, the value is just unchanged.
    text = "MARKETING_VERSION = 2.1.0;\n"
    assert bump_text("project.pbxproj", text, "2.1.0") == text


def test_bump_plist_idempotent_when_already_at_target() -> None:
    text = "<key>CFBundleShortVersionString</key>\n<string>2.1.0</string>\n"
    assert bump_text("Info.plist", text, "2.1.0") == text


def test_bump_pbxproj_without_marketing_version_errors() -> None:
    with pytest.raises(AviatoError):
        bump_text("project.pbxproj", "OTHER_SETTING = 1;\n", "2.0.0")


def test_bump_plist_without_short_version_errors() -> None:
    with pytest.raises(AviatoError):
        bump_text("Info.plist", "<key>Other</key>\n<string>x</string>\n", "2.0.0")


def test_bump_pbxproj_build_number_required_when_supplied() -> None:
    # A swift release supplies a build number; if CURRENT_PROJECT_VERSION is absent the
    # bump MUST fail loudly, not silently drop the monotonic build number (§13.4). A
    # silent drop ships a duplicate CFBundleVersion that App Store Connect rejects.
    with pytest.raises(AviatoError):
        bump_text("project.pbxproj", "MARKETING_VERSION = 1.0.0;\n", "2.0.0", build_number="42")


def test_bump_plist_build_number_required_when_supplied() -> None:
    text = "<key>CFBundleShortVersionString</key>\n<string>1.0.0</string>\n"
    with pytest.raises(AviatoError):
        bump_text("Info.plist", text, "2.0.0", build_number="42")


def test_bump_pyproject_single_quoted_version() -> None:
    # TOML allows single-quoted strings; a valid PEP 621 file using version = '1.2.3'
    # must bump (preserving the quote style), not raise "no version field".
    text = "[project]\nname = 'x'\nversion = '1.2.3'\n"
    out = bump_text("pyproject.toml", text, "2.0.0")
    assert "version = '2.0.0'" in out


def test_bump_pbxproj_tolerates_alternate_spacing_around_equals() -> None:
    # A hand-edited project.pbxproj may not use Xcode's canonical single spaces around
    # '='; the rewriter must still find the field (preserving the original spacing).
    assert "MARKETING_VERSION=2.0.0;" in bump_text("project.pbxproj", "MARKETING_VERSION=1.0.0;\n", "2.0.0")


def test_bump_files_rewrites_existing_locations(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    changed = bump_files(tmp_path, ["pyproject.toml", "missing.toml"], "1.1.0")
    assert changed == ["pyproject.toml"]
    assert 'version = "1.1.0"' in (tmp_path / "pyproject.toml").read_text()
