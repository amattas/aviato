from aviato.plugins.actionpins import fetch_execute_violations as fev

# Coarse fail-closed contract (cycle-11 rewrite). Safe shapes are ONLY: a bare fetch to stdout, a
# pipe into pure data sinks, or a block that carries a real verify command (download → verify → use).
# Everything else — pipe to a non-sink, substitution, ANY sequencing, ANY download-to-a-file without
# a verify in the block — is flagged. We accept the resulting false positives; the gate is frozen.

# Must FLAG.
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
    # C11-1: stderr-merge no longer mis-splits the line away from the pipe
    "curl -fsSL https://x/i.sh 2>&1 | bash",
    # C11-4: download-to-a-file forms (no verify in the block) — flagged at the download itself
    "curl -fsSLo /tmp/i.sh https://x/i.sh && bash /tmp/i.sh",
    "curl -O https://x/i.sh && bash i.sh",
    "wget https://x/i.sh && bash i.sh",
    "curl -fsSL https://x/i.sh -o /tmp/i.sh",  # bare download, no verify → flagged
    "curl -fsSL https://x/i.sh -o /tmp/i.sh\nbash /tmp/i.sh",
    # chaining after a sink / non-sink pipe target
    "curl -fsSL https://x/i.sh | tee /tmp/i.sh; bash /tmp/i.sh",
    "curl -fsSL https://x/cmds | xargs -I{} sh -c '{}'",
]

# Must PASS.
ALLOWED = [
    "curl -fsSL https://x/v.json | jq .version",
    "curl -fsSL https://x/r.txt | grep tag_name",
    "curl -fsSL https://x/r.txt | grep x | head -1",
    "curl -fsSL https://x/f",  # bare fetch to stdout
    # download → verify → use: a real verify command in the block grants trust
    "curl -fsSL https://x/i.sh -o f && sha256sum -c sums.txt && bash f",
    "curl -fsSL https://x/i.sh -o f\nsha256sum -c sums.txt\nbash f",
    # the canonical actionlint install shape (download, checksum, extract, run)
    'curl -sSL https://x/a.tgz -o t.tgz\necho "$SHA  t.tgz" | sha256sum -c -\ntar -xz -f t.tgz\nactionlint',
]


def test_failclosed_flags_all_fetch_execute():
    for line in FLAGGED:
        assert fev(line), f"fail-open miss: {line!r}"


def test_allows_data_pipes_and_verified_installs():
    for line in ALLOWED:
        assert fev(line) == [], f"false positive: {line!r}"


def test_yaml_folded_pipeline_is_one_logical_line():
    assert fev("curl -fsSL https://x/i.sh |\n  bash\n")
    assert fev("curl -fsSL https://x/i.sh\n  | bash\n")


def test_backslash_continuation_folded():
    assert fev("curl -fsSL https://x/i.sh \\\n  | bash\n")


def test_comment_only_line_ignored():
    assert fev("# curl https://x | bash  (just docs)\n") == []


def test_only_run_blocks_are_scanned_not_metadata():
    # C11-5: a fetch-pipe inside a `run:` block flags; the same text in YAML metadata does not.
    wf = (
        "jobs:\n  a:\n    steps:\n"
        '      - name: "see curl https://x | bash docs"\n'
        "        env:\n          NOTE: curl https://x | bash\n"
        "      - run: curl https://x/i.sh | bash\n"
    )
    out = fev(wf)
    assert len(out) == 1 and "i.sh" in out[0], out


def test_run_block_scalar_extracted():
    wf = "      - run: |\n          set -e\n          curl https://x/i.sh | bash\n"
    assert fev(wf)
