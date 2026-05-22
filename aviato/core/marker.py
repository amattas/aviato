from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# The marker uses a caller-supplied comment prefix; the per-filetype mapping is
# plug-in data (see aviato.plugins.comment_syntax), keeping this module agnostic.

_TOKEN = "aviato:managed"
# The marker line must be led by the file's comment syntax (§6.2): a run of comment
# punctuation (e.g. ``#``, ``//``, ``/*``, ``<!--``) — never letters/digits — so the
# token appearing mid-prose is not mistaken for a marker. The hash is the hex content
# digest; an optional trailing run of comment punctuation tolerates block-comment
# closers (e.g. ``*/``, ``-->``) without swallowing them into the hash.
_LEAD = r"[^\sA-Za-z0-9]+"
_CLOSE = r"(?:\s+[^\sA-Za-z0-9]+)?"
_MARKER_RE = re.compile(
    rf"^\s*{_LEAD}\s+aviato:managed\s+profile=(?P<profile>\S+)\s+version=(?P<version>\S+)"
    rf"\s+hash=(?P<hash>[0-9a-fA-F]+){_CLOSE}\s*$"
)


@dataclass(frozen=True)
class MarkerInfo:
    profile: str
    version: str
    hash: str


def content_hash(body: str) -> str:
    """SHA-256 of the rendered body with line endings normalized to ``\\n`` (§5.5)."""
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def render_marker(*, profile: str, version: str, body: str, comment: str) -> str:
    """Render the canonical managed-marker line (§6.2) for ``body``."""
    return f"{comment} {_TOKEN} profile={profile} version={version} hash={content_hash(body)}"


def parse_marker(line: str) -> MarkerInfo | None:
    """Parse a single line into :class:`MarkerInfo`, or None if absent/malformed.

    A line carrying the ``aviato:managed`` token but not matching the exact
    grammar is malformed → None (the caller treats that as dirty-drift, §5.4).
    """
    if _TOKEN not in line:
        return None
    match = _MARKER_RE.search(line)
    if not match:
        return None
    return MarkerInfo(profile=match.group("profile"), version=match.group("version"), hash=match.group("hash"))


def parse_marker_from_text(text: str) -> MarkerInfo | None:
    """Parse the marker from a file's text: the first non-blank line is the marker (§6.2)."""
    for line in text.splitlines():
        if line.strip():
            return parse_marker(line)
    return None


def strip_marker_from_text(text: str) -> str:
    """Remove the managed-marker line from a file's text, leaving a plain file (§5.13).

    If the first non-blank line is a valid marker it is dropped; otherwise the
    text is returned unchanged.
    """
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip():
            if parse_marker(line) is not None:
                return "".join(lines[:i] + lines[i + 1 :])
            return text
    return text
