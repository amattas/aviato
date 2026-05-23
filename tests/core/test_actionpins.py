from __future__ import annotations

from aviato.plugins.actionpins import unpinned_third_party_uses, unpinned_tool_invocations

_SHA = "a" * 40


def test_flags_third_party_mutable_tag() -> None:
    text = "jobs:\n  x:\n    steps:\n      - uses: docker/build-push-action@v5\n"
    assert unpinned_third_party_uses(text) == ["docker/build-push-action@v5"]


def test_third_party_pinned_to_sha_is_ok() -> None:
    text = f"      - uses: docker/build-push-action@{_SHA}\n"
    assert unpinned_third_party_uses(text) == []


def test_first_party_actions_are_exempt() -> None:
    text = "      - uses: actions/checkout@v4\n      - uses: github/codeql-action/init@v3\n"
    assert unpinned_third_party_uses(text) == []


def test_local_and_reusable_refs_skipped() -> None:
    text = "    uses: ./.github/actions/x\n    uses: amattas/aviato/.github/workflows/reusable-python-ci.yml@v1\n"
    assert unpinned_third_party_uses(text) == []


def test_non_library_reusable_workflow_mutable_ref_is_flagged() -> None:
    # §11.3: only the consumer's own Library reference is the sanctioned mutable ref; a
    # THIRD-PARTY reusable workflow must be digest-pinned, not exempted as "a reusable ref".
    text = "    uses: other-org/repo/.github/workflows/build.yml@main\n"
    assert unpinned_third_party_uses(text) == ["other-org/repo/.github/workflows/build.yml@main"]


def test_non_library_reusable_workflow_sha_is_ok() -> None:
    text = "    uses: other-org/repo/.github/workflows/build.yml@" + "a" * 40 + "\n"
    assert unpinned_third_party_uses(text) == []


def test_flags_non_exact_pip_specs() -> None:
    # §11.3: a pin must be EXACT. A range/compatible/wildcard spec is still floating.
    for spec in ("foo>=1.0", "foo~=1.0", "foo<=2", "foo!=1.5", "foo==1.*"):
        text = f"          python -m pip install --quiet {spec}\n"
        out = unpinned_tool_invocations(text)
        assert out == [f"pip-installed tool not pinned to an exact version: {spec}"], spec


def test_exact_pip_pin_is_ok() -> None:
    for spec in ("foo==1.2.3", "foo===1.2.3", "pkg[extra]==2.0.0"):
        text = f"          python -m pip install {spec}\n"
        assert unpinned_tool_invocations(text) == [], spec


def test_flags_docker_run_image_without_digest() -> None:
    text = "          docker run --rm -i hadolint/hadolint hadolint -\n"
    assert unpinned_tool_invocations(text) == ["docker run image not digest-pinned: hadolint/hadolint"]


def test_docker_run_image_with_digest_is_ok() -> None:
    text = "          docker run --rm -i hadolint/hadolint@sha256:" + "a" * 64 + " hadolint -\n"
    assert unpinned_tool_invocations(text) == []


def test_docker_sha256_in_other_arg_does_not_mask_unpinned_image() -> None:
    # review #9: an `@sha256:` in an unrelated arg (e.g. --label) must NOT mask an unpinned image.
    text = "          docker run evil:latest --label x@sha256:" + "a" * 64 + "\n"
    assert unpinned_tool_invocations(text) == ["docker run image not digest-pinned: evil:latest"]


def test_docker_value_taking_flag_does_not_shift_detected_image() -> None:
    # review #D: a value-taking flag (`-e VAR=x`) must not shift the detected image token.
    text = "          docker run --rm -e FOO=bar -v /a:/b alpine:3.19 echo\n"
    assert unpinned_tool_invocations(text) == ["docker run image not digest-pinned: alpine:3.19"]


def test_flags_curl_piped_to_shell_or_tar() -> None:
    text = "          curl -sSL https://example.com/releases/download/v1/tool.tar.gz | sudo tar -xz -C /usr/local/bin\n"
    out = unpinned_tool_invocations(text)
    assert out and "fetch-and-execute without checksum" in out[0]


def test_curl_to_file_then_checksum_is_ok() -> None:
    text = (
        "          curl -sSL https://example.com/tool.tar.gz -o /tmp/t.tar.gz\n"
        '          echo "abc  /tmp/t.tar.gz" | sha256sum -c -\n'
        "          tar -xz -C /usr/local/bin -f /tmp/t.tar.gz\n"
    )
    assert unpinned_tool_invocations(text) == []


def test_flags_floating_pip_install() -> None:
    # §11.3: a pip-installed tool with no exact version is a floating latest.
    text = "          python -m pip install --quiet pydoc-markdown\n"
    out = unpinned_tool_invocations(text)
    assert out == ["pip-installed tool not pinned to an exact version: pydoc-markdown"]


def test_pinned_pip_install_is_ok() -> None:
    text = '          python -m pip install --quiet "pydoc-markdown==4.8.2"\n'
    assert unpinned_tool_invocations(text) == []


def test_pip_install_local_vcs_wheel_and_requirements_are_skipped() -> None:
    # Local editable, extras, VCS, wheel, requirements file, and yamllint==$VER are not
    # floating index-package installs and must NOT be flagged (conservative checker).
    text = (
        "          python -m pip install -e .[dev]\n"
        "          python -m pip install git+https://github.com/amattas/aviato@1.2.3\n"
        '          python -m pip install "dist"/*.whl\n'
        "          python -m pip install -r requirements.txt\n"
        '          python -m pip install --quiet "yamllint==${YAMLLINT_VERSION}"\n'
    )
    assert unpinned_tool_invocations(text) == []


def test_pip_env_marker_is_not_flagged() -> None:
    # §11.3: a PEP 508 environment marker is not a floating package — the exact-pinned spec is
    # accepted and the marker fragment (quote-bearing) is ignored (no false positive).
    text = "          python -m pip install \"foo==1.2.3; python_version<'3.9'\"\n"
    assert unpinned_tool_invocations(text) == []


def test_pip_direct_reference_is_not_flagged() -> None:
    # `name @ url` is a direct reference (the URL pins it), not a floating index package.
    text = "          python -m pip install foo @ git+https://example.com/foo.git\n"
    assert unpinned_tool_invocations(text) == []


def test_pip_env_marker_still_flags_a_floating_spec() -> None:
    # The marker carve-out must not mask a genuinely floating spec on the same line.
    text = "          python -m pip install \"foo>=1.0; python_version<'3.9'\"\n"
    out = unpinned_tool_invocations(text)
    assert any("foo>=1.0" in v for v in out)


def test_action_pin_scan_covers_yaml_extension(tmp_path) -> None:
    # §11.3: a `.yaml` workflow must not escape the digest-pin scan (GitHub accepts both exts).
    from aviato.plugins.actionpins import action_pin_violations

    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "build.yaml").write_text("jobs:\n  x:\n    steps:\n      - uses: other/action@main\n", encoding="utf-8")
    violations = action_pin_violations(tmp_path)
    assert any("other/action@main" in v for v in violations)


def test_pip_glued_env_marker_still_flags_floating_spec() -> None:
    # §11.3: a floating spec GLUED to its marker with no space (`foo>=1.0;python_version<'3.9'`)
    # must still be flagged — the marker is split off before the quote-skip (L-3 regression).
    text = "          python -m pip install \"foo>=1.0;python_version<'3.9'\"\n"
    out = unpinned_tool_invocations(text)
    assert out == ["pip-installed tool not pinned to an exact version: foo>=1.0"]


def test_pip_glued_exact_pin_with_marker_is_ok() -> None:
    text = "          python -m pip install \"foo==1.2.3;python_version<'3.9'\"\n"
    assert unpinned_tool_invocations(text) == []


def test_lint_definition_file_exempt_from_tool_invocation_scan(tmp_path) -> None:
    # §11.3: the in-CI lint DEFINITION embeds the docker/fetch detector patterns (grep args +
    # comments); the text scan can't tell those from real invocations, so reusable-common-lint.yml
    # is exempt from the tool-invocation scan (its real invocations are pinned + reviewed). A
    # DIFFERENT file with the same content is still flagged.
    from aviato.plugins.actionpins import action_pin_violations

    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    body = "jobs:\n  x:\n    steps:\n      - run: |\n          docker run hadolint/hadolint hadolint -\n"
    (wf / "reusable-common-lint.yml").write_text(body, encoding="utf-8")
    (wf / "other.yml").write_text(body, encoding="utf-8")
    violations = action_pin_violations(tmp_path)
    assert not any("reusable-common-lint.yml" in v and "docker run" in v for v in violations)
    assert any("other.yml" in v and "docker run" in v for v in violations)
