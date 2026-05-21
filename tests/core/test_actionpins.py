from __future__ import annotations

from aviato.core.actionpins import unpinned_third_party_uses

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
