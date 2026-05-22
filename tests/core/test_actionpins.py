from __future__ import annotations

from aviato.core.actionpins import unpinned_third_party_uses, unpinned_tool_invocations

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


def test_flags_docker_run_image_without_digest() -> None:
    text = "          docker run --rm -i hadolint/hadolint hadolint -\n"
    assert unpinned_tool_invocations(text) == ["docker run image not digest-pinned: hadolint/hadolint"]


def test_docker_run_image_with_digest_is_ok() -> None:
    text = "          docker run --rm -i hadolint/hadolint@sha256:" + "a" * 64 + " hadolint -\n"
    assert unpinned_tool_invocations(text) == []


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
