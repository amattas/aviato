from __future__ import annotations

import re
from pathlib import Path

# §11.3: third-party actions/tools must be pinned by commit digest (40-hex SHA).
# GitHub's own namespaces are first-party and exempt.
_FIRST_PARTY_OWNERS = {"actions", "github"}
_USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _is_third_party(action_ref: str) -> bool:
    # Skip local (./...) and reusable-workflow (contains .github/workflows) references.
    if action_ref.startswith("./") or "/.github/workflows/" in action_ref:
        return False
    owner = action_ref.split("/", 1)[0]
    return owner not in _FIRST_PARTY_OWNERS


def unpinned_third_party_uses(text: str) -> list[str]:
    """Return third-party ``uses:`` refs in a workflow not pinned to a commit SHA (§11.3)."""
    violations: list[str] = []
    for ref in _USES_RE.findall(text):
        if "@" not in ref:
            continue
        action, _, version = ref.partition("@")
        if _is_third_party(action) and not _SHA_RE.match(version):
            violations.append(ref)
    return violations


# §11.3 covers shell-fetched tools/images too, not just `uses:` refs. Two well-defined
# anti-patterns are detected: a `docker run` image without an `@sha256:` digest, and a
# remote artifact fetched and piped straight into a shell/extractor (no checksum gate).
_DOCKER_RUN_RE = re.compile(r"\bdocker\s+run\b(?P<rest>[^\n]*)")
_FETCH_PIPE_RE = re.compile(r"\b(?:curl|wget)\b[^\n|]*\|[^\n]*\b(?:sh|bash|tar)\b")


def unpinned_tool_invocations(text: str) -> list[str]:
    """Return shell-invoked tools/images not pinned by digest/checksum (§11.3)."""
    violations: list[str] = []
    for match in _DOCKER_RUN_RE.finditer(text):
        image = _docker_run_image(match.group("rest"))
        if image is not None and "@sha256:" not in image:
            violations.append(f"docker run image not digest-pinned: {image}")
    for match in _FETCH_PIPE_RE.finditer(text):
        violations.append(f"fetch-and-execute without checksum: {match.group(0).strip()}")
    return violations


def _docker_run_image(rest: str) -> str | None:
    """The image argument of a ``docker run`` invocation: the first non-flag token.

    Skips option flags (``--rm``, ``-i``) — valueless flags only; a flag taking a
    separate value (``-e VAR``) would shift the image, so the detector is a best-effort
    guard for the common pinning mistake, paired with the digest check above.
    """
    for token in rest.split():
        if token.startswith("-"):
            continue
        return token
    return None


def action_pin_violations(root: Path) -> list[str]:
    """Scan workflows + scaffolded workflow bodies for unpinned third-party actions.

    Returns ``file: ref`` strings. Placeholders like ``@{{ aviato-ref }}`` in scaffold
    bodies are skipped (they pin the Library, resolved at scaffold time).
    """
    root = Path(root)
    targets = list((root / ".github" / "workflows").glob("*.yml"))
    targets += list((root / "aviato" / "library" / "scaffold" / "files").glob("wf-*.yml"))
    violations: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for ref in unpinned_third_party_uses(text):
            if "{{" in ref:  # scaffold placeholder, not a real mutable tag
                continue
            violations.append(f"{path.name}: {ref}")
        for tool in unpinned_tool_invocations(text):
            violations.append(f"{path.name}: {tool}")
    return violations
