from __future__ import annotations

from aviato.core.marker import (
    content_hash,
    parse_marker,
    parse_marker_from_text,
    render_marker,
)
from aviato.plugins.comment_syntax import COMMENT_SYNTAX, comment_for_path


def test_render_and_parse_roundtrip_hash_comment() -> None:
    body = "line1\nline2\n"
    line = render_marker(profile="python-library", version="v1", body=body, comment="#")
    assert line.startswith("# aviato:managed profile=python-library version=v1 hash=")
    info = parse_marker(line)
    assert info is not None
    assert info.profile == "python-library"
    assert info.version == "v1"
    assert info.hash == content_hash(body)


def test_render_with_double_slash_comment() -> None:
    line = render_marker(profile="p", version="v1", body="x\n", comment="//")
    assert line.startswith("// aviato:managed ")
    info = parse_marker(line)
    assert info is not None and info.profile == "p"


def test_hash_excludes_line_endings() -> None:
    assert content_hash("a\r\nb\r\n") == content_hash("a\nb\n")


def test_malformed_marker_returns_none() -> None:
    assert parse_marker("# aviato:managed profile=x") is None  # missing version/hash
    assert parse_marker("# just a comment") is None


def test_token_in_prose_is_not_a_marker() -> None:
    # §6.2: the marker is led by the file's comment syntax. A line where the token
    # appears mid-prose (not led by a comment prefix) must NOT parse as a marker.
    assert parse_marker("see docs aviato:managed profile=p version=v1 hash=abcdef") is None


def test_marker_tolerates_trailing_block_comment_closer() -> None:
    # A block-comment style with a trailing closer must round-trip: the closer must
    # not be swallowed into the hash (which would permanently misclassify the file).
    info = parse_marker("<!-- aviato:managed profile=p version=v1 hash=abcdef -->")
    assert info is not None
    assert info.hash == "abcdef"
    assert info.profile == "p"


def test_first_nonblank_line_is_the_marker() -> None:
    text = "\n\n# aviato:managed profile=p version=v1 hash=abc\nbody\n"
    info = parse_marker_from_text(text)
    assert info is not None and info.profile == "p"


def test_text_without_marker_parses_none() -> None:
    assert parse_marker_from_text("plain file\n") is None


def test_strip_marker_removes_first_marker_line() -> None:
    from aviato.core.marker import strip_marker_from_text

    text = "# aviato:managed profile=p version=v1 hash=abc\nbody line\n"
    assert strip_marker_from_text(text) == "body line\n"


def test_strip_marker_leaves_unmarked_text_unchanged() -> None:
    from aviato.core.marker import strip_marker_from_text

    assert strip_marker_from_text("plain\nbody\n") == "plain\nbody\n"


def test_comment_for_path_maps_extensions() -> None:
    assert comment_for_path("a.py") == "#"
    assert comment_for_path("a.ts") == "//"
    assert comment_for_path("a.yaml") == "#"
    assert comment_for_path("a.swift") == "//"
    assert comment_for_path("a.unknownext") is None
    assert ".py" in COMMENT_SYNTAX


def test_control_byte_prefix_is_not_a_valid_marker_lead() -> None:
    # review #19: the lead must be comment punctuation, never control bytes — a NUL/control-byte
    # prefix used to satisfy `[^\sA-Za-z0-9]+` and let a binary blob spoof the marker lead.
    from aviato.core.marker import parse_marker, parse_marker_from_text

    spoof = "\x00\x00# aviato:managed profile=p version=1.0.0 hash=ab"
    assert parse_marker(spoof) is None
    assert parse_marker_from_text(spoof) is None
    # Real comment leads still parse (regression guard).
    for lead in ("#", "//", "/*", "<!--", ";", "%"):
        ok = f"{lead} aviato:managed profile=p version=1.0.0 hash=ab"
        assert parse_marker(ok) is not None, lead
