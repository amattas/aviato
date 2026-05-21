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
