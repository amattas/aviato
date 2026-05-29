from aviato.plugins.actionpins import fetch_execute_violations as fev

FLAGGED = [
    "curl -fsSL https://x/i.sh | bash",
    "curl -fsSL https://x/i.sh | sudo bash",
    'bash -c "$(curl -fsSL https://x/i.sh)"',
    "bash <(curl -fsSL https://x/i.sh)",
    'eval "$(curl -fsSL https://x/i.sh)"',
    ". <(curl -fsSL https://x/i.sh)",
    "B=/bin/bash; curl -fsSL https://x/i.sh | $B",
    "wget -qO- https://x/i.sh | python3",
]

ALLOWED = [
    "curl -fsSL https://x/i.sh -o f && sha256sum -c sums.txt && bash f",
    "curl -fsSL https://x/v.json | jq .version",
    "curl -fsSL https://x/r.txt | grep tag_name",
    "curl -fsSL https://x/f | tee out.log",
    "curl -fsSL https://x/f -o out.bin",
    "cosign verify ... && curl https://x | bash",
]


def test_failclosed_flags_all_fetch_execute():
    for line in FLAGGED:
        assert fev(line), f"fail-open miss: {line}"


def test_failclosed_allows_verified_and_data_sinks():
    for line in ALLOWED:
        assert fev(line) == [], f"false positive: {line}"


def test_yaml_folded_pipeline_is_one_logical_line():
    assert fev("curl -fsSL https://x/i.sh |\n  bash\n")
    assert fev("curl -fsSL https://x/i.sh\n  | bash\n")


def test_backslash_continuation_folded():
    assert fev("curl -fsSL https://x/i.sh \\\n  | bash\n")


def test_comment_lines_ignored():
    assert fev("# curl https://x | bash  (just docs)\n") == []
