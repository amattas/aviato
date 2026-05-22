from __future__ import annotations

# Per-filetype comment-syntax mapping used to render/parse managed markers
# (§6.2). This is filetype knowledge that names language-specific extensions, so
# it lives in the plug-in tree, not the agnostic core. A TemplateModule carries
# its own ``comment`` value; this map is a convenience for callers that only
# know an output path.
COMMENT_SYNTAX: dict[str, str] = {
    ".py": "#",
    ".yml": "#",
    ".yaml": "#",
    ".toml": "#",
    ".cfg": "#",
    ".ini": "#",
    ".sh": "#",
    ".rb": "#",
    ".ts": "//",
    ".tsx": "//",
    ".js": "//",
    ".jsx": "//",
    ".mjs": "//",
    ".cjs": "//",
    ".swift": "//",
    ".go": "//",
    ".rs": "//",
    ".java": "//",
    ".kt": "//",
}


def comment_for_path(path: str) -> str | None:
    """Return the comment prefix for ``path``'s extension, or None if unmapped."""
    dot = path.rfind(".")
    if dot == -1:
        return None
    return COMMENT_SYNTAX.get(path[dot:])
