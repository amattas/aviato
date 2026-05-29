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
    assert unpinned_tool_invocations(text) == ["docker image not digest-pinned: hadolint/hadolint"]


def test_docker_run_image_with_digest_is_ok() -> None:
    text = "          docker run --rm -i hadolint/hadolint@sha256:" + "a" * 64 + " hadolint -\n"
    assert unpinned_tool_invocations(text) == []


def test_flags_docker_pull_image_without_digest() -> None:
    # CX#7: `docker pull` is just as much a mutable-image risk as `docker run`; the checker must
    # flag it too (it previously only matched `docker run`, diverging from the in-CI shell gate).
    assert unpinned_tool_invocations("          docker pull alpine:3.19\n") == [
        "docker image not digest-pinned: alpine:3.19"
    ]
    assert unpinned_tool_invocations("          docker pull alpine@sha256:" + "a" * 64 + "\n") == []


def test_docker_sha256_in_other_arg_does_not_mask_unpinned_image() -> None:
    # review #9: an `@sha256:` in an unrelated arg (e.g. --label) must NOT mask an unpinned image.
    text = "          docker run evil:latest --label x@sha256:" + "a" * 64 + "\n"
    assert unpinned_tool_invocations(text) == ["docker image not digest-pinned: evil:latest"]


def test_docker_value_taking_flag_does_not_shift_detected_image() -> None:
    # review #D: a value-taking flag (`-e VAR=x`) must not shift the detected image token.
    text = "          docker run --rm -e FOO=bar -v /a:/b alpine:3.19 echo\n"
    assert unpinned_tool_invocations(text) == ["docker image not digest-pinned: alpine:3.19"]


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
    assert not any("reusable-common-lint.yml" in v and "docker image" in v for v in violations)
    assert any("other.yml" in v and "docker image" in v for v in violations)


def test_action_pin_scan_flags_unpinned_docker_pull_end_to_end(tmp_path) -> None:
    # R5-12: CX#7 has unit coverage of the `docker pull` matcher, but no end-to-end fixture proved
    # the repo-level scan (what `aviato validate` runs) actually surfaces it. A workflow that pulls
    # a mutable tag must fail the scan; the digest-pinned form must not.
    from aviato.plugins.actionpins import action_pin_violations

    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "bad.yml").write_text(
        "jobs:\n  x:\n    steps:\n      - run: |\n          docker pull alpine:3.19\n", encoding="utf-8"
    )
    (wf / "good.yml").write_text(
        "jobs:\n  y:\n    steps:\n      - run: |\n          docker pull alpine@sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    violations = action_pin_violations(tmp_path)
    assert any("bad.yml" in v and "docker image not digest-pinned" in v for v in violations)
    assert not any("good.yml" in v for v in violations)


def test_unpinned_requirements_lines_flags_floors_not_exact() -> None:
    # R4-4/R4-5: a CI-installed requirements file must pin tools exactly; a `>=` floor lets a run
    # pull an untested newer tool (§11.3). The line scanner flags floors/bare names, accepts `==`,
    # and ignores comments/blank lines.
    from aviato.plugins.actionpins import unpinned_requirements_lines

    body = "# header comment\npytest>=8.0\nmypy==1.13.0\n\nruff  # inline note\n"
    flagged = unpinned_requirements_lines(body)
    assert any("pytest>=8.0" in f for f in flagged)
    assert any(f == "ruff" for f in flagged)
    assert not any("mypy" in f for f in flagged)


def test_action_pin_scan_flags_floor_pinned_seeded_dev_requirements(tmp_path) -> None:
    # R4-5: the `pip install -r requirements-dev.txt` reference is (correctly) skipped by the
    # package-token scan — the path isn't a package — so a floor INSIDE the seeded file was
    # invisible. The repo-level scan now reads the seed body directly and flags it.
    from aviato.plugins.actionpins import action_pin_violations

    seeds = tmp_path / "aviato" / "library" / "scaffold" / "files"
    seeds.mkdir(parents=True)
    (seeds / "requirements-dev.txt.txt").write_text("pytest>=8.0\nruff==0.8.0\n", encoding="utf-8")
    violations = action_pin_violations(tmp_path)
    assert any("requirements-dev.txt.txt" in v and "pytest>=8.0" in v for v in violations)
    assert not any("ruff" in v for v in violations)


def test_fetch_pipe_detects_non_shell_interpreters() -> None:
    # R2-2-SC1: a fetch piped into any interpreter is fetch-and-execute, not just sh/bash/tar.
    from aviato.plugins.actionpins import unpinned_tool_invocations

    for interp in ("python", "python3", "node", "nodejs", "ruby", "perl", "pwsh", "php"):
        out = unpinned_tool_invocations(f"          curl https://x | {interp}\n")
        assert out, interp
    # A pipe into a non-interpreter (e.g. jq, grep) is not a fetch-and-execute.
    assert unpinned_tool_invocations("          curl https://x | jq .\n") == []


def test_uses_with_space_before_colon_is_still_checked() -> None:
    # R2-2-USES: YAML allows `uses : x`; the digest check must not be evaded by the space.
    from aviato.plugins.actionpins import unpinned_third_party_uses

    assert unpinned_third_party_uses("      - uses : third/action@main\n") == ["third/action@main"]
    assert unpinned_third_party_uses("      - uses : third/action@" + "a" * 40 + "\n") == []


def test_docker_image_pull_subcommand_and_full_digest_validation() -> None:
    # R2-2-DOCKER: `docker image pull`/`docker container run` are covered, and a digest must be a
    # full 64-hex sha256 (a truncated/typo'd digest must NOT pass as pinned).
    from aviato.plugins.actionpins import unpinned_tool_invocations

    assert unpinned_tool_invocations("          docker image pull alpine:3.19\n")
    assert unpinned_tool_invocations("          docker container run alpine:3.19 echo\n")
    assert unpinned_tool_invocations("          docker pull alpine@sha256:abc\n")  # short → flagged
    assert unpinned_tool_invocations("          docker pull alpine@sha256:" + "a" * 64 + "\n") == []  # full → ok


def test_fetch_pipe_does_not_flag_interpreter_as_an_argument() -> None:
    # R3-1-FETCHARG: the interpreter must be the COMMAND right after the pipe, not merely a token
    # downstream — `curl | grep python` (python is grep's arg) is NOT fetch-and-execute.
    from aviato.plugins.actionpins import unpinned_tool_invocations

    assert unpinned_tool_invocations("          curl https://x | grep python\n") == []
    assert unpinned_tool_invocations("          curl https://x | tee node.log\n") == []


def test_fetch_pipe_flags_wrapped_interpreters_no_fail_open() -> None:
    # R4-2-FETCHNEG/R4-5-A: anchoring the interpreter must NOT re-open a fail-open — a real
    # fetch-and-execute can prefix the interpreter with sudo (incl. options), command/exec,
    # nice/nohup/time, env, or a bare VAR=val assignment. ALL of these MUST be flagged. (The earlier
    # test only asserted the false-positive removal, which silently certified these as "covered".)
    from aviato.plugins.actionpins import unpinned_tool_invocations

    must_flag = (
        "curl https://x | bash",
        "curl https://x | bash -s",
        "curl https://x |bash",  # no space after pipe
        "wget -qO- https://x | python3",
        "curl https://x 2>/dev/null | sh -e",
        "curl https://x | tee x | bash",  # intermediate pipe
        "curl https://x | sudo bash",
        "curl https://x | sudo -E bash",  # sudo WITH options
        "curl https://x | sudo -H python3",
        "curl https://x | command bash",
        "curl https://x | exec bash",
        "curl https://x | nohup bash",
        "curl https://x | env FOO=bar bash",
        "curl https://x | NODE_ENV=production node",  # bare inline assignment
    )
    for cmd in must_flag:
        assert unpinned_tool_invocations(f"          {cmd}\n"), f"fetch-and-execute not flagged (fail-open): {cmd}"


def test_tool_scan_ignores_full_comment_lines() -> None:
    # R3-1-DOCKERX: a prose/comment line mentioning a command is documentation, not an invocation.
    from aviato.plugins.actionpins import unpinned_tool_invocations

    assert unpinned_tool_invocations("          # you can docker run a container later\n") == []
    assert unpinned_tool_invocations("          # e.g. curl https://x | bash to install\n") == []
    # The nonexistent cross-product `docker image run` is no longer matched (only valid forms are).
    assert unpinned_tool_invocations("          docker image run alpine:3.19\n") == []


def test_fetch_pipe_no_false_positive_on_interpreter_prefixed_command() -> None:
    # R5-1-FP: the detector must end the interpreter at a real command boundary — a tool whose NAME
    # merely starts with an interpreter token (followed by -, ., or /) is NOT fetch-and-execute.
    from aviato.plugins.actionpins import unpinned_tool_invocations

    for benign in (
        "curl https://x | node-gyp rebuild",
        "curl https://x | python-foo",
        "curl https://x | tar.bin -xz",
        "curl https://x | nodejs-thing",
        "curl https://x | shellcheck",
    ):
        assert unpinned_tool_invocations(f"          {benign}\n") == [], benign


def test_fetch_pipe_flags_absolute_path_interpreters() -> None:
    # R5-1-FN: an absolute/explicit path to the interpreter (incl. /usr/bin/env) is still fetch-and-execute.
    from aviato.plugins.actionpins import unpinned_tool_invocations

    for c in (
        "curl https://x | /bin/bash",
        "curl https://x | /usr/local/bin/python3",
        "curl https://x | /usr/bin/env bash",
    ):
        assert unpinned_tool_invocations(f"          {c}\n"), c


def test_action_pin_scan_tolerates_non_utf8_workflow(tmp_path) -> None:
    # R5-4-LINT: `lint-actions <consumer>` scans operator-supplied workflows; a non-UTF-8 file must
    # not leak a raw UnicodeDecodeError — it's read with errors="replace" (the scan is substring).
    # R6-3-LINT-WEAK: the assertion must prove the scan CONTINUED through the degraded file (and
    # still flagged its unpinned `uses:`), not just "didn't raise" — a regression that wraps the
    # read in try/except-continue would silently skip the file and the old isinstance-only assert
    # would still pass.
    from aviato.plugins.actionpins import action_pin_violations

    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "bad.yml").write_bytes(b"\xff\xfejobs:\n  x:\n    steps:\n      - uses: other/a@main\x00\n")
    violations = action_pin_violations(tmp_path)  # must not raise
    assert any("other/a@main" in v for v in violations), "scan must still surface the unpinned ref"


def test_fetch_pipe_flags_path_prefixed_wrappers() -> None:
    # R6-1-PATHWRAP: an absolute-path WRAPPER (`/usr/bin/sudo`, `/usr/bin/command`, etc.) is a
    # real fetch-and-execute and must be flagged — the F cycle's path prefix was originally added
    # only to `env`, asymmetric, leaving the others as a §11.3 fail-open.
    from aviato.plugins.actionpins import unpinned_tool_invocations

    for wrap in ("sudo", "command", "exec", "nice", "nohup", "time"):
        cmd = f"curl https://x | /usr/bin/{wrap} bash"
        assert unpinned_tool_invocations(f"          {cmd}\n"), cmd
    # Chained wrappers (nohup wrapping sudo wrapping the interpreter).
    assert unpinned_tool_invocations("          curl https://x | /usr/bin/nohup /usr/bin/sudo bash\n")


def test_fetch_pipe_flags_sudo_value_flags_and_doas_and_env_with_flags() -> None:
    # R6-1-SUDOVAL: `sudo` with value-taking flags (`-u user`/`-g grp`), `doas` (BSD's sudo), and
    # `env -i FOO=bar bash` all evaded before — each is fetch-and-execute and must be flagged.
    from aviato.plugins.actionpins import unpinned_tool_invocations

    for cmd in (
        "curl https://x | sudo -u root bash",
        "curl https://x | sudo -g grp bash",
        "curl https://x | sudo -E -u root bash",
        "curl https://x | doas bash",
        "curl https://x | doas -u root bash",
        "curl https://x | env -i FOO=bar bash",
    ):
        assert unpinned_tool_invocations(f"          {cmd}\n"), cmd


def test_fetch_pipe_flags_value_taking_wrapper_flags_and_added_launchers() -> None:
    # R7-2-WRAPVAL: every wrapper now uniformly accepts `-flag [value]` (negative-lookahead value-
    # token so the interpreter is never swallowed) AND `taskset/chrt/ionice/setsid/stdbuf/unshare/
    # setpriv/runuser/timeout` are now in the wrapper set. `timeout` accepts a bare-duration first
    # positional. All forms below MUST flag.
    from aviato.plugins.actionpins import unpinned_tool_invocations

    cases = (
        # value-taking flags on the previously-narrow wrappers
        "curl u | nice -n 10 bash",
        "curl u | time -o log.txt bash",
        "curl u | env -u VAR bash",
        "curl u | env -C dir bash",
        "curl u | sudo --user root bash",
        "curl u | time --output log bash",
        "curl u | nice --adjustment 10 bash",
        "curl u | env -S 'x' bash",
        # previously-absent launchers
        "curl u | taskset -c 0 bash",
        "curl u | chrt -f 50 bash",
        "curl u | ionice -c 3 bash",
        "curl u | setsid bash",
        "curl u | stdbuf -oL bash",
        "curl u | unshare -n bash",
        "curl u | setpriv --reuid=1000 bash",
        "curl u | runuser -u user bash",
        # timeout's bare-duration first positional
        "curl u | timeout 30 bash",
        "curl u | timeout 5m bash",
    )
    for c in cases:
        assert unpinned_tool_invocations(f"          {c}\n"), c
    # FP guards: a non-wrapper or a value that happens to look like an interpreter must NOT match.
    for benign in ("curl u | mytool -x value bash_data.txt", "curl u | nice -n 10 myfile.txt", "curl u | jq .name"):
        assert unpinned_tool_invocations(f"          {benign}\n") == [], benign


# ----------------------------------------------------------------------------------------------
# Historical edge-case corpus for the fetch-and-execute detector.
#
# The fetch-pipe detector was edited five cycles in a row (DA/EA/FA/GB/HB) — each cycle found a
# new wrapper or flag form the prior regex didn't cover, and each "fix" was a regex restructure.
# That kind of flapping is a sign that the wrong tool was being used: shell idioms are open-ended
# (`sudo -u user`, `/usr/bin/env`, `nice -n 10`, `timeout 30`, `doas -C dir`, `env FOO=bar`, …),
# and an enumerated regex never converges.
#
# The current implementation is a shlex-based tokenizer over a CLOSED set of wrappers and a
# CLOSED set of interpreters — new shell conventions become one-line list edits, not regex
# restructures. To freeze that property, the test below is the union of every edge case the
# six prior reviews found (TPs that must continue to be flagged, FPs that must continue NOT to
# be flagged). A regression here is a test failure, not a follow-up review finding.
# ----------------------------------------------------------------------------------------------

_FETCH_PIPE_HISTORICAL_TRUE_POSITIVES = (
    # canonical forms
    "curl https://x | bash",
    "curl https://x | bash -s",
    "curl https://x |bash",  # no-space after pipe
    "wget -qO- https://x | python3",
    "curl https://x | tee x | bash",  # intermediate-pipe
    # privilege wrappers (with + without options)
    "curl https://x | sudo bash",
    "curl https://x | sudo -E bash",
    "curl https://x | sudo -u root bash",
    "curl https://x | sudo -g grp bash",
    "curl https://x | sudo -E -u root bash",
    "curl https://x | sudo --user root bash",
    "curl https://x | doas bash",
    "curl https://x | doas -u root bash",
    # path-prefixed wrappers
    "curl https://x | /usr/bin/sudo bash",
    "curl https://x | /usr/bin/command bash",
    "curl https://x | /usr/bin/exec bash",
    "curl https://x | /usr/bin/nice bash",
    "curl https://x | /usr/bin/nohup bash",
    "curl https://x | /usr/bin/time bash",
    "curl https://x | /usr/bin/nohup /usr/bin/sudo bash",
    # absolute-path interpreters
    "curl https://x | /bin/bash",
    "curl https://x | /usr/local/bin/python3",
    "curl https://x | /usr/bin/env bash",
    # named wrappers
    "curl https://x | command bash",
    "curl https://x | exec bash",
    "curl https://x | nohup bash",
    # env / inline assignments
    "curl https://x | env FOO=bar bash",
    "curl https://x | env -i FOO=bar bash",
    "curl https://x | env -u VAR bash",
    "curl https://x | env -C dir bash",
    "curl https://x | NODE_ENV=production node",
    # nice / time value-flags
    "curl https://x | nice -n 10 bash",
    "curl https://x | time -o log.txt bash",
    "curl https://x | time --output log bash",
    "curl https://x | nice --adjustment 10 bash",
    "curl https://x | env -S 'x' bash",
    # newer launchers added in cluster HB
    "curl https://x | taskset -c 0 bash",
    "curl https://x | chrt -f 50 bash",
    "curl https://x | ionice -c 3 bash",
    "curl https://x | setsid bash",
    "curl https://x | stdbuf -oL bash",
    "curl https://x | unshare -n bash",
    "curl https://x | setpriv --reuid=1000 bash",
    "curl https://x | runuser -u user bash",
    # timeout's bare-duration first positional
    "curl https://x | timeout 30 bash",
    "curl https://x | timeout 5m bash",
    # interpreter variety
    "curl https://x | tar xz",
    "wget -qO- https://x | python3",
    # R8-1-PROCSUB: process substitution routes the stream into the inner command. The outer
    # "first command" (`tee`) is benign — only the inner is the executor.
    "curl https://x | tee >(bash)",
    'curl https://x | tee >(sh -c "$(cat)")',  # nested-paren: needs balanced-paren extractor
    "curl https://x | tee >(python3)",
    # R8-2-SUBST: command substitution can yield an interpreter literal (`$(echo bash)`) or
    # contain one (`$(... bash ...)`); backtick form too.
    "curl https://x | $(echo bash)",
    "curl https://x | `echo bash`",
    # R8-3-WRAPPERS: privilege/sandbox/lock/group wrappers that were unknown in earlier cycles.
    "curl https://x | sg root bash",
    "curl https://x | systemd-run --pipe bash",
    "curl https://x | flock /tmp/x bash",
    "curl https://x | firejail bash",
    "curl https://x | bwrap bash",
    "curl https://x | chroot /jail bash",
    "curl https://x | watch bash",
    "curl https://x | strace bash",
    "curl https://x | parallel bash ::: a b",
    "curl https://x | eatmydata bash",
    "curl https://x | poetry run python",
    # R8-5-CONT: shell line-continuation between fetch and interpreter must not evade.
    "curl https://x | \\\n  bash",
    "curl -sSL https://x | \\\n  sudo bash",
    # R8-6-BUILTINS: source/./eval are bash builtins that execute their argument as code.
    "curl https://x | source /dev/stdin",
    "curl https://x | . /dev/stdin",
    'curl https://x | eval "$(cat)"',
    # R8-10-INTERP-INCOMPLETE: additional interpreters added to `_INTERPRETERS`.
    "curl https://x | lua -",
    "curl https://x | tclsh",
    "curl https://x | awk -f -",
    "curl https://x | sed -f -",
    "curl https://x | osascript -",
    "curl https://x | Rscript -",
    "curl https://x | groovy -",
    "curl https://x | swift -",
)

_FETCH_PIPE_HISTORICAL_FALSE_POSITIVE_GUARDS = (
    # interpreter-name-as-argument (R3-1-FETCHARG / R5-1-FP)
    "curl https://x | grep python",
    "curl https://x | tee node.log",
    "curl https://x | jq .name",
    # interpreter-name-as-prefix-of-another-command (R5-1-FP)
    "curl https://x | node-gyp rebuild",
    "curl https://x | python-foo",
    "curl https://x | tar.bin",
    "curl https://x | nodejs-thing",
    "curl https://x | shellcheck",
    # relative path is NOT the interpreter
    "curl https://x | foo/bar/bash",
    # wrapper with a value-flag whose value happens to be a benign filename
    "curl https://x | nice -n 10 myfile.txt",
    "curl https://x | mytool -x value bash_data.txt",
    # R8-14-FP-TWINS: adversarial twins per TP class — each FP below targets the SAME detector
    # path as a TP above, so a sloppy widening of the detector would flip the FP to True.
    #   * twin for `tee >(bash)`         — proc-sub whose inner is benign
    "curl https://x | tee >(grep ERROR)",
    "curl https://x | tee >(node.log)",  # inner basename `node.log` is NOT `node`
    #   * twin for `$(echo bash)`        — cmd-sub whose body has no interpreter
    "echo hi | $(date)",
    "echo hi | $(cat /tmp/x)",
    #   * twin for `sg root bash`        — sg with a non-interpreter command
    "curl https://x | sg root ls",
    #   * twin for `flock /tmp/x bash`   — flock with a non-interpreter command
    "curl https://x | flock /tmp/x ls",
    #   * twin for `chroot /jail bash`   — chroot with a non-interpreter command (and an R-like
    #     positional `/r` that must NOT be misread as the R interpreter)
    "curl https://x | chroot /r ls",
    "curl https://x | chroot /jail ls",
    #   * twin for `timeout 30 bash`     — timeout with a non-interpreter command
    "curl https://x | timeout 30 ls",
    #   * twin for `awk -f -`            — awk consuming a literal file, not stdin
    "curl https://x | awk-script-file.txt",
    #   * twin for `poetry run python`   — poetry/pipenv subcommands OTHER than `run` do not
    #     execute the following token; without `run`-gating, `poetry add bash` would FP.
    "curl https://x | poetry add bash",
    "curl https://x | pipenv install bash",
)


def test_fetch_pipe_historical_edge_case_corpus() -> None:
    # Locked invariant: every TP/FP edge case found across review cycles DA/EA/FA/GB/HB/HA-HL
    # (the five flapping cycles plus this convergence cycle) is regression-frozen here. A future
    # review must NOT need to re-discover any of these — the tokenizer-based detector handles them
    # uniformly, so the test corpus is the spec.
    from aviato.plugins.actionpins import unpinned_tool_invocations

    misses, false_positives = [], []
    for cmd in _FETCH_PIPE_HISTORICAL_TRUE_POSITIVES:
        if not unpinned_tool_invocations(f"          {cmd}\n"):
            misses.append(cmd)
    for cmd in _FETCH_PIPE_HISTORICAL_FALSE_POSITIVE_GUARDS:
        if unpinned_tool_invocations(f"          {cmd}\n"):
            false_positives.append(cmd)
    assert not misses, "fetch-and-execute regressions (missed):\n  - " + "\n  - ".join(misses)
    assert not false_positives, "fetch-and-execute regressions (false positive):\n  - " + "\n  - ".join(false_positives)
