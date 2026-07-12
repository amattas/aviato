import pytest

from aviato.plugins.actionpins import (
    action_pin_violations,
    unpinned_requirements_lines,
    unpinned_third_party_uses,
    unpinned_tool_invocations,
)

_SHA = "a" * 40


# --- uses: SHA check (kept for scaffold bodies; placeholder-aware in action_pin_violations) ---


def test_flags_third_party_mutable_tag():
    assert unpinned_third_party_uses("      - uses: docker/build-push-action@v5\n") == ["docker/build-push-action@v5"]


def test_third_party_pinned_to_sha_is_ok():
    assert unpinned_third_party_uses(f"      - uses: a/b@{_SHA}\n") == []


def test_first_party_and_library_self_ref_exempt():
    assert unpinned_third_party_uses("      - uses: actions/checkout@v4\n") == []
    assert unpinned_third_party_uses("      - uses: amattas/aviato/.github/workflows/x.yml@v1\n") == []


def test_uses_with_space_before_colon_still_checked():
    assert unpinned_third_party_uses("      - uses : third/action@main\n") == ["third/action@main"]


# --- pip exact-version (kept) ---


def test_flags_floating_pip_install():
    out = unpinned_tool_invocations("          pip install build pytest>=8\n")
    assert "build" in str(out) and "pytest>=8" in str(out)


def test_exact_pip_pin_is_ok():
    assert unpinned_tool_invocations("          pip install build==1.2.3\n") == []


def test_pip_local_vcs_wheel_requirements_skipped():
    # §11.3: local paths, -r requirements files, and wheels stay exempt. A VCS token now
    # requires a full commit SHA (see test_vcs_pip_installs_require_full_commit_sha below),
    # so the VCS token here is pinned to a 40-hex SHA rather than the old bare `git+https://x`.
    text = (
        "          pip install . -e ./pkg -r reqs.txt "
        "git+https://github.com/squidfunk/mike.git@2d4ad799442f4592db8ad53b179bfb33db8c69ac "
        "dist/a.whl\n"
    )
    assert unpinned_tool_invocations(text) == []


def test_unpinned_requirements_lines_flags_floors_not_exact():
    body = "pytest>=8.0\nruff==0.8.0\n# comment\nbuild\n"
    flagged = unpinned_requirements_lines(body)
    assert "pytest>=8.0" in flagged and "build" in flagged and "ruff==0.8.0" not in flagged


# --- end-to-end (zizmor stubbed so the unit suite is hermetic) ---


def test_action_pin_scan_flags_floor_seeded_requirements(tmp_path, monkeypatch):
    from aviato.plugins import zizmor_scan

    monkeypatch.setattr(zizmor_scan, "zizmor_uses_image_violations", lambda _d: [])
    seed = tmp_path / "aviato" / "library" / "scaffold" / "files"
    seed.mkdir(parents=True)
    (seed / "requirements-dev.txt.txt").write_text("pytest>=8.0\n", encoding="utf-8")
    out = action_pin_violations(tmp_path)
    assert any("pytest>=8.0" in v for v in out)


def test_action_pin_scan_flags_fetch_execute_in_workflow(tmp_path, monkeypatch):
    from aviato.plugins import zizmor_scan

    monkeypatch.setattr(zizmor_scan, "zizmor_uses_image_violations", lambda _d: [])
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("        run: curl https://x/i.sh | bash\n", encoding="utf-8")
    out = action_pin_violations(tmp_path)
    assert any("fetch-and-execute" in v for v in out)


def test_pip_glued_env_marker_still_flags_floating_spec() -> None:
    # §11.3: a floating spec GLUED to its marker with no space (`foo>=1.0;python_version<'3.9'`)
    # must still be flagged — the marker is split off before the quote-skip (L-3 regression).
    text = "          python -m pip install \"foo>=1.0;python_version<'3.9'\"\n"
    out = unpinned_tool_invocations(text)
    assert out == ["pip-installed tool not pinned to an exact version: foo>=1.0"]


def test_pip_glued_exact_pin_with_marker_is_ok() -> None:
    text = "          python -m pip install \"foo==1.2.3;python_version<'3.9'\"\n"
    assert unpinned_tool_invocations(text) == []


def test_flags_npx_that_can_fetch_floating_registry_tool() -> None:
    text = "          npx eslint .\n"
    assert unpinned_tool_invocations(text) == ["npx may fetch an unpinned registry tool: npx eslint ."]


def test_npx_no_install_is_ok() -> None:
    text = "          npx --no-install eslint .\n"
    assert unpinned_tool_invocations(text) == []


def test_npx_exact_package_fetch_is_ok() -> None:
    text = "          npx -y -p typedoc@0.27.9 -p typedoc-plugin-markdown@4.4.1 typedoc \\\n"
    assert unpinned_tool_invocations(text) == []


def test_flags_npx_package_fetch_without_exact_version() -> None:
    text = "          npx -y -p typedoc -p typedoc-plugin-markdown@latest typedoc\n"
    out = unpinned_tool_invocations(text)
    expected = "npx may fetch an unpinned registry tool: npx -y -p typedoc -p typedoc-plugin-markdown@latest typedoc"
    assert out == [expected]


def test_action_pin_scan_surfaces_zizmor_uses_finding(tmp_path, monkeypatch):
    from aviato.plugins import zizmor_scan

    monkeypatch.setattr(zizmor_scan, "zizmor_uses_image_violations", lambda _d: ["unpinned-uses: ci.yml"])
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push\n", encoding="utf-8")
    out = action_pin_violations(tmp_path)
    assert any("unpinned-uses" in v for v in out)


def test_action_pin_scan_tolerates_non_utf8_workflow(tmp_path, monkeypatch):
    from aviato.plugins import zizmor_scan

    monkeypatch.setattr(zizmor_scan, "zizmor_uses_image_violations", lambda _d: [])
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "bad.yml").write_bytes(b"\xff\xfe not utf8")
    action_pin_violations(tmp_path)  # must not raise


def test_seeded_pyproject_dev_extras_must_be_exact_pinned():
    """finding 12: floors in the seeded pyproject's extras floated invisibly — CI installs
    them via `pip install -e .[dev]`, which the pip-token scan correctly exempts."""
    from aviato.plugins.actionpins import unpinned_pyproject_extra_lines

    text = (
        "[project]\n"
        'name = "{{ distribution-name }}"\n'
        "[project.optional-dependencies]\n"
        "dev = [\n"
        '  "pytest>=8.0",\n'
        '  "ruff==0.8.0",\n'
        '  "{{ tool-placeholder }}",\n'
        "]\n"
        "[tool.other]\n"
        '"quoted-but-outside>=1"\n'
    )
    assert unpinned_pyproject_extra_lines(text) == ["pytest>=8.0"]


def test_pyproject_extras_scanner_covers_inline_arrays_and_single_quotes():
    """second-review fix: a valid-TOML reformat (inline array, single quotes, nested
    extras table) must not disable the §11.3 extras gate."""
    from aviato.plugins.actionpins import unpinned_pyproject_extra_lines

    text = (
        "[project.optional-dependencies]\n"
        'dev = ["black>=24.1.0", "pytest==8.0.0"]\n'
        "lint = [\n"
        "  'ruff>=0.8.0',\n"
        "]\n"
        "[project.optional-dependencies.docs]\n"
        'x = ["sphinx>=7"]\n'
        "[tool.other]\n"
        'y = ["quoted-but-outside>=1"]\n'
    )
    assert unpinned_pyproject_extra_lines(text) == ["black>=24.1.0", "ruff>=0.8.0", "sphinx>=7"]


_MIKE_SHA = "2d4ad799442f4592db8ad53b179bfb33db8c69ac"


@pytest.mark.parametrize(
    ("token", "flagged"),
    [
        (f"git+https://github.com/squidfunk/mike.git@{_MIKE_SHA}", False),
        (f"mike @ git+https://github.com/squidfunk/mike.git@{_MIKE_SHA}", False),
        ("git+https://github.com/squidfunk/mike.git", True),
        ("git+https://github.com/squidfunk/mike.git@master", True),
        ("git+https://github.com/squidfunk/mike.git@2d4ad79", True),
        (f"mike @ git+https://github.com/squidfunk/mike.git@{_MIKE_SHA[:12]}", True),
        ("GIT+https://github.com/squidfunk/mike.git@master", True),
    ],
)
def test_vcs_pip_installs_require_full_commit_sha(token: str, flagged: bool) -> None:
    from aviato.plugins.actionpins import _unpinned_pip_packages

    result = _unpinned_pip_packages(f" {token}")
    assert bool(result) is flagged, result


def test_bad_direct_reference_flags_exactly_once() -> None:
    from aviato.plugins.actionpins import _unpinned_pip_packages

    result = _unpinned_pip_packages(f" mike @ git+https://github.com/squidfunk/mike.git@{_MIKE_SHA[:12]}")
    assert result == ["mike"]


def test_bare_bad_vcs_flags_exactly_once() -> None:
    from aviato.plugins.actionpins import _unpinned_pip_packages

    token = "git+https://github.com/squidfunk/mike.git@master"
    result = _unpinned_pip_packages(f" {token}")
    assert result == [token]


def test_vcs_scheme_case_insensitive_gate() -> None:
    from aviato.plugins.actionpins import _unpinned_pip_packages

    token = "GIT+https://github.com/squidfunk/mike.git@master"
    result = _unpinned_pip_packages(f" {token}")
    assert result == [token]


def test_unpinned_requirements_lines_vcs_contract() -> None:
    body = (
        f"mike @ git+https://github.com/squidfunk/mike.git@{_MIKE_SHA}  # comment\n"
        "git+https://github.com/squidfunk/mike.git@master\n"
    )
    flagged = unpinned_requirements_lines(body)
    assert flagged.count("git+https://github.com/squidfunk/mike.git@master") == 1
    assert "mike" not in flagged
    assert not any("2d4ad799442f4592db8ad53b179bfb33db8c69ac" in item for item in flagged)
