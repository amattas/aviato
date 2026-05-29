from aviato.plugins.actionpins import fetch_execute_violations as fev

# Must FLAG — these execute fetched bytes. Includes the cycle-9 bypasses (R9-1..R9-4) AND the
# cycle-10 fail-open holes (R10-1 checksum-word, R10-2 chaining-after-sink, R10-N1 fetch-to-file).
FLAGGED = [
    # direct stream → interpreter
    "curl -fsSL https://x/i.sh | bash",
    "curl -fsSL https://x/i.sh | sudo bash",
    "wget -qO- https://x/i.sh | python3",
    # substitution forms
    'bash -c "$(curl -fsSL https://x/i.sh)"',
    "bash <(curl -fsSL https://x/i.sh)",
    'eval "$(curl -fsSL https://x/i.sh)"',
    ". <(curl -fsSL https://x/i.sh)",
    "B=/bin/bash; curl -fsSL https://x/i.sh | $B",
    # R10-1: a checksum WORD does not prove anything — comment / string / URL / unrelated tool
    "curl -fsSL https://x/i.sh | bash  # TODO add sha256sum later",
    'echo "we should cosign this" && curl -fsSL https://x/i.sh | bash',
    "curl -fsSL https://x/sha256sum/i.sh | bash",
    "gpg --version >/dev/null; curl -fsSL https://x/i.sh | bash",
    "sha256sum --version; curl -fsSL https://x/i.sh | bash",
    # R10-2: executor chained after an allowlisted/data sink
    "curl -fsSL https://x/i.sh | tee /tmp/i.sh; bash /tmp/i.sh",
    "curl -fsSL https://x/i.sh | cat > /tmp/i.sh && bash /tmp/i.sh",
    "curl -fsSL https://x/p.json | jq -r .script > /tmp/i.sh && bash /tmp/i.sh",
    # R10-N1: fetch-to-file then run (incl. cross-line)
    "curl -fsSL https://x/i.sh -o /tmp/i.sh; sh /tmp/i.sh",
    "curl -fsSL https://x/i.sh -o /tmp/i.sh\nbash /tmp/i.sh",
    "wget -q https://x/i.sh -O /tmp/i.sh\n. /tmp/i.sh",
    # pipe into a non-pure sink that can execute (xargs)
    "curl -fsSL https://x/cmds | xargs -I{} sh -c '{}'",
]

# Must PASS — legitimate, must not flag (usability).
ALLOWED = [
    "curl -fsSL https://x/v.json | jq .version",
    "curl -fsSL https://x/r.txt | grep tag_name",
    "curl -fsSL https://x/r.txt | grep x | head -1",
    "curl -fsSL https://x/f",  # bare fetch to stdout, goes nowhere
    "curl -fsSL https://x/f -o out.bin",  # downloaded, never referenced again in this block
    # the canonical SAFE pattern: download → real verify command → then use
    "curl -fsSL https://x/i.sh -o f && sha256sum -c sums.txt && bash f",
    "curl -fsSL https://x/i.sh -o f\nsha256sum -c sums.txt\nbash f",
]


def test_failclosed_flags_all_fetch_execute():
    for line in FLAGGED:
        assert fev(line), f"fail-open miss: {line!r}"


def test_failclosed_allows_data_pipelines_and_verified_installs():
    for line in ALLOWED:
        assert fev(line) == [], f"false positive: {line!r}"


def test_yaml_folded_pipeline_is_one_logical_line():
    assert fev("curl -fsSL https://x/i.sh |\n  bash\n")
    assert fev("curl -fsSL https://x/i.sh\n  | bash\n")


def test_backslash_continuation_folded():
    assert fev("curl -fsSL https://x/i.sh \\\n  | bash\n")


def test_comment_only_line_ignored():
    assert fev("# curl https://x | bash  (just docs)\n") == []
