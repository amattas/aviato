from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# The marker uses a caller-supplied comment prefix; the per-filetype mapping is
# plug-in data (see aviato.plugins.comment_syntax), keeping this module agnostic.

_TOKEN = "aviato:managed"
# The marker line must be led by the file's comment syntax (§6.2): a run of comment
# punctuation (e.g. ``#``, ``//``, ``/*``, ``<!--``) — never letters/digits, and never
# CONTROL bytes (review #19: ``[^\sA-Za-z0-9]`` alone matched NUL/control prefixes, letting a
# binary blob spoof the comment lead). The ``\x00-\x1f\x7f`` exclusion keeps every real comment
# punctuation char while rejecting control bytes, so a binary file is never read as marked. The
# hash is the hex content digest; an optional trailing run of comment punctuation tolerates
# block-comment closers (e.g. ``*/``, ``-->``) without swallowing them into the hash.
# The ``version`` group stays ``\S+`` on purpose: the marker is parsed STRUCTURALLY here, then
# the recorded version is validated SEMANTICALLY by the caller (is_known_version_pin / §2.6
# is_compatible, both fail-closed). That distinction lets diagnosis tell "a valid aviato marker
# recording an unknown version" (dirty-drift / skipped_foreign — migration or tamper) apart from
# "no marker at all" (skipped_unmanaged — operator's own file); tightening it here would conflate
# the two. The version is never executed — only compared and stamped — so an exotic token is inert.
_PUNCT = r"[^\sA-Za-z0-9\x00-\x1f\x7f]+"
_LEAD = _PUNCT
_CLOSE = rf"(?:\s+{_PUNCT})?"
_MARKER_RE = re.compile(
    rf"^\s*{_LEAD}\s+aviato:managed\s+profile=(?P<profile>\S+)\s+version=(?P<version>\S+)"
    rf"\s+hash=(?P<hash>[0-9a-fA-F]+)(?:\s+inputs=(?P<input_hash>[0-9a-fA-F]{{64}}))?{_CLOSE}\s*$"
)


@dataclass(frozen=True)
class MarkerInfo:
    profile: str
    version: str
    hash: str
    input_hash: str | None


def content_hash(body: str) -> str:
    """SHA-256 of the rendered body with line endings normalized to ``\\n`` (§5.5)."""
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonical_input_hash(values: Mapping[str, Any]) -> str:
    """SHA-256 identity of canonical resolved, non-secret inputs."""
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_marker(*, profile: str, version: str, body: str, comment: str, input_hash: str) -> str:
    """Render the canonical managed-marker line (§6.2) for ``body``."""
    return f"{comment} {_TOKEN} profile={profile} version={version} hash={content_hash(body)} inputs={input_hash}"


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
    return MarkerInfo(
        profile=match.group("profile"),
        version=match.group("version"),
        hash=match.group("hash"),
        input_hash=match.group("input_hash"),
    )


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
