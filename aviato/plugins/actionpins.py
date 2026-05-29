from __future__ import annotations

import re
from pathlib import Path

# §11.3: third-party actions/tools must be pinned by commit digest (40-hex SHA).
# GitHub's own namespaces are first-party and exempt.
_FIRST_PARTY_OWNERS = {"actions", "github"}
# The consumer's pinned Library reference is the ONE sanctioned mutable ref (a floating
# major advances on every release, §6.1/§11.3); its own reusable workflows are exempt.
# Any OTHER org's reusable workflow is third-party and must be digest-pinned like an action
# — a blanket `/.github/workflows/` exemption would let `other-org/repo/...@main` through.
_LIBRARY_SLUG = "amattas/aviato"
_LIBRARY_REUSABLE_PREFIX = f"{_LIBRARY_SLUG}/.github/workflows/"
# R2-2-USES: `uses\s*:` — YAML accepts a space before the mapping colon (`uses : x`), so a literal
# `uses:` match would let `uses : third/action@main` evade the digest-pin check.
_USES_RE = re.compile(r"^\s*(?:-\s*)?uses\s*:\s*([^\s#]+)", re.MULTILINE)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _is_third_party(action_ref: str) -> bool:
    # Local (``./...``) refs and the consumer's own Library reference are exempt; every other
    # owner — including a non-Library reusable-workflow ref — is third-party (§11.3).
    if action_ref.startswith("./") or action_ref.startswith(_LIBRARY_REUSABLE_PREFIX):
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


# §11.3 FAIL-CLOSED fetch-execute detection. DO NOT re-introduce interpreter enumeration: that fails
# OPEN (an unknown interpreter/wrapper = a silent miss) and flapped for 8 commits (cycle-9 R9-1..R9-5);
# the first fail-closed cut still had fail-OPEN edges — a checksum WORD anywhere on the line, and an
# executor chained after an allowlisted sink (cycle-10 R10-1/R10-2/R10-N1). This rule is the INVERSE
# and convergent: it enumerates only OBVIOUSLY-SAFE pure data sinks + a real verify COMMAND, and
# treats everything else fetched bytes can reach as a violation. There is nothing to enumerate on the
# danger side — new executors are caught by default. The safe shapes are exactly two: a pure data
# pipeline (`curl … | jq`) and download → verify → use.
_FETCH_RE = re.compile(r"\b(?:curl|wget)\b")
# An executing substitution next to a fetch: process-sub `<(`/`>(`, command-sub `$(`, backtick. A
# stream into one of these cannot be checksum-gated → always a violation.
_SUBST_RE = re.compile(r"<\(|>\(|\$\(|`")
# PURE data sinks: consume stdin, emit to stdout/console only — they neither execute their input nor
# write a file. Deliberately EXCLUDES tee/redirects (file write → taint), awk/sed (`-f`/`-e` execute),
# xargs, and every shell/interpreter (the danger we do NOT enumerate — those fall through to violation).
_PURE_SINKS = frozenset(
    {"jq", "grep", "egrep", "fgrep", "rg", "head", "tail", "sort", "uniq", "wc", "cut", "tr", "less", "more", "nl"}
)
# A REAL verify COMMAND (verb + check mode), not a bare mention — clears download-file taint so the
# canonical "download → verify → use" pattern passes. A comment/URL/`--version` does NOT match (R10-1).
_VERIFY_RE = re.compile(
    r"\b(?:sha(?:1|256|512)sum|shasum|b2sum|md5sum)\b[^\n]*?(?:\s-c\b|\s--check\b)"
    r"|\bcosign\s+verify(?:-blob)?\b"
    r"|\bgpg\b[^\n]*?\s--(?:verify|decrypt)\b"
    r"|\bminisign\b[^\n]*?\s-V\b"
)
# Command-sequence separators (NOT the single pipe `|`, which stays within one pipeline/command).
_SEQ_RE = re.compile(r"&&|\|\||;|&")
_OUT_FLAG_RE = re.compile(r"(?:^|\s)(?:-o|-O|--output)(?:=|\s+)(\S+)")
_REDIR_RE = re.compile(r">>?\s*(\S+)")
_TEE_RE = re.compile(r"\btee\b\s+((?:-\S+\s+)*)(\S+)")


def _strip_comments(text: str) -> str:
    """Drop shell line comments (`#` at line start or after whitespace, to EOL). A `#` mid-token (a
    URL fragment) is preserved. Comments must never be able to satisfy a safety check (R10-1)."""
    return re.sub(r"(?m)(^|\s)#.*$", r"\1", text)


def _fold_logical_lines(text: str) -> list[str]:
    """Fold `\\`-newline continuations and split-pipe scalars into logical lines. Folding only JOINS,
    so it can add flags, never remove them (fail-closed safe; closes the cycle-9 R9-2 fold cases)."""
    text = re.sub(r"\\\n[ \t]*", " ", text)  # shell line-continuation
    text = re.sub(r"\|[ \t]*\n[ \t]*", "| ", text)  # pipe at EOL → join with next
    text = re.sub(r"\n[ \t]*\|", " |", text)  # pipe leads next line → join with prev
    return text.splitlines()


def _basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _download_targets(unit: str) -> set[str]:
    """Files an unverified download writes in this command unit (curl -o / `>` redirect / tee)."""
    targets: set[str] = set(_OUT_FLAG_RE.findall(unit))
    targets.update(_REDIR_RE.findall(unit))
    for _flags, name in _TEE_RE.findall(unit):
        targets.add(name)
    return {t for t in targets if not t.startswith(("&", "/dev/")) and t != "-"}


def _fetch_streams_into_executor(unit: str) -> bool:
    """A fetch unit whose output streams into execution: an executing substitution, or a pipe whose
    downstream is anything other than a pure data sink or `tee` (a file write, handled via taint)."""
    if _SUBST_RE.search(unit):
        return True
    for segment in unit.split("|")[1:]:
        tokens = segment.split()
        if not tokens:
            return True  # dangling pipe — cannot prove safe
        head = _basename(tokens[0])
        if head not in _PURE_SINKS and head != "tee":
            return True  # a possible executor (bash/sh/python/xargs/$VAR/…) — not enumerated, just "not safe"
    return False


def fetch_execute_violations(text: str) -> list[str]:
    """Fail-closed §11.3 fetch-execute check (design contract in the module comment above).

    Walks the comment-stripped, folded text as an ORDERED sequence of command units (split on
    ``;``/``&&``/``||``/``&``; the pipe ``|`` stays within a unit). A downloaded file is TAINTED; a
    real verify command clears taint. A unit is a violation when it (a) contains a fetch that streams
    into an executing substitution or a non-pure-sink pipe target, or (b) uses a tainted download that
    no verify command has cleared. Only a pure data pipeline (`curl … | jq`) and download → verify →
    use are clean.
    """
    violations: list[str] = []
    tainted: set[str] = set()
    for line in _fold_logical_lines(_strip_comments(text)):
        if not line.strip():
            continue
        for unit in _SEQ_RE.split(line):
            if not unit.strip():
                continue
            if _VERIFY_RE.search(unit):
                tainted.clear()  # operator gated integrity for the sequence
                continue
            if _FETCH_RE.search(unit):
                if _fetch_streams_into_executor(unit):
                    violations.append(f"fetch-and-execute without checksum: {line.strip()}")
                else:
                    tainted |= _download_targets(unit)  # download(s) to file → tainted until verified
                continue
            if tainted:
                tokens = set(unit.split()) | {_basename(t) for t in unit.split()}
                if tainted & tokens:
                    violations.append(f"unverified downloaded file used: {line.strip()}")
    return violations


# §11.3: a tool installed from a package index that exposes no digest (a pip package)
# must be pinned to an EXACT version, never a floating latest. Match a `pip install`
# invocation and inspect the package tokens after it.
_PIP_INSTALL_RE = re.compile(r"\bpip[0-9]*\s+install\b(?P<rest>[^\n]*)")
# The package-name portion of a pip token (optionally with an extras spec), e.g. `build`,
# `pydoc-markdown`, `pkg[extra]`. Used after stripping any version specifier to identify a
# real index package (vs a path/URL/var) so a NON-exact spec can still be reported by name.
_PIP_PKG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?$")
# Any PEP 440 version operator; used to split a token into its name and to detect a spec.
_PIP_VERSION_OP_RE = re.compile(r"(===|==|>=|<=|~=|!=|<|>)")


def _unpinned_pip_packages(rest: str) -> list[str]:
    """PyPI package tokens in a `pip install` arg list that are NOT pinned to an exact version.

    §11.3 requires an **exact** version (`name==X.Y.Z`), never a floating latest. So a bare
    name (`build`) AND a non-exact specifier (`foo>=1.0`, `foo~=1.0`, the wildcard `foo==1.*`)
    are all flagged; only a concrete `==`/`===` pin with no wildcard is accepted. Excludes
    things that are not a plain index package: option flags, the local project
    (`.`/`.[extra]`/`-e <path>`), requirements/constraints files, VCS (`git+…`), built wheels
    (`*.whl`), URLs, and shell-variable tokens (`${…}`) — conservative, so a legitimate
    local/VCS install never trips it.

    PEP 508 **environment markers** (``foo==1.0; python_version<'3.9'``) and **direct
    references** (``foo @ git+…``) are NOT flagged: the marker fragment (a quote-bearing token)
    is ignored, and a name immediately followed by ``@`` is a direct reference, not a floating
    index package — both would otherwise be false positives.

    R8-12-PIP-WHITESPACE: PEP 440 §VersionSpecifiers permits whitespace around the operator
    (``foo == 1.2.3`` is a valid exact pin), but a plain ``rest.split()`` would emit three tokens
    `['foo', '==', '1.2.3']` and the bare `foo` would be wrongly flagged as floating. Collapse the
    whitespace around any PEP 440 operator into the canonical no-space form before tokenizing.
    """
    rest = re.sub(r"\s*(===|==|>=|<=|~=|!=|<|>)\s*", r"\1", rest)
    tokens = rest.split()
    flagged: list[str] = []
    skip_next = False
    for index, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        stripped = token.strip("'\"")
        if stripped in ("-r", "--requirement", "-c", "--constraint"):
            skip_next = True  # the following token is a file path, not a package
            continue
        if stripped.startswith("-"):  # any other flag (-e, --quiet, --upgrade, …)
            continue
        # Drop any PEP 508 environment marker BEFORE evaluating — the spec is everything before
        # the `;`. This handles both the spaced (`foo>=1.0; python_version<'3.9'`, marker is a
        # separate token) and GLUED (`foo>=1.0;python_version<'3.9'`, one token) forms, so a
        # genuinely floating spec glued to a marker is not silently dropped by the quote-skip.
        spec = stripped.split(";", 1)[0].strip().strip("'\"")
        # A marker fragment (the part after `;`, surfacing as its own token in the spaced form)
        # carries an inner quote that survives the outer-quote strip — not a package. Skip it.
        if "'" in spec or '"' in spec:
            continue
        # A PEP 508 direct reference `name @ url`: the next token is `@`. Not a floating index
        # package (the URL/VCS ref pins it), so don't flag the bare name.
        if index + 1 < len(tokens) and tokens[index + 1].strip("'\"") == "@":
            continue
        # Not a plain index package: path, VCS/URL, wheel, or shell variable.
        if any(marker in spec for marker in ("@", "/", "$", ":")) or spec.endswith(".whl"):
            continue
        if spec in (".", "") or spec.startswith("."):
            continue
        # An EXACT pin (`name==X.Y.Z` / `===`) with no wildcard is the only acceptable form.
        if ("==" in spec or "===" in spec) and "*" not in spec:
            continue
        # Bare name or a non-exact specifier (>=, ~=, <=, !=, ==1.*) → not exactly pinned.
        name = _PIP_VERSION_OP_RE.split(spec, 1)[0]
        if _PIP_PKG_RE.match(name):
            flagged.append(spec)
    return flagged


def unpinned_requirements_lines(text: str) -> list[str]:
    """Requirement lines in a SEEDED requirements file that are not pinned to an exact version.

    R4-4/R4-5: a requirements file the consumer CI installs with ``pip install -r`` is itself a
    supply-chain surface, but the ``-r <file>`` reference is (correctly) skipped by the package
    scanner — the path is not a package — so a floor pin (``pytest>=8.0``) inside it was invisible
    to the gate and let CI silently pull an untested newer tool (§11.3). Each non-comment line is a
    single requirement; reuse the same exact-pin rule as ``pip install`` tokens (a bare name or any
    non-``==`` specifier is flagged). Inline ``# …`` comments and blank lines are ignored.
    """
    flagged: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            flagged.extend(_unpinned_pip_packages(line))
    return flagged


def unpinned_tool_invocations(text: str) -> list[str]:
    """Shell-invoked tools not pinned (§11.3): fail-closed fetch-execute + non-exact pip installs.

    Container-image pinning (`container:`/`services:`) is handled by zizmor's `unpinned-images`;
    ad-hoc `docker run img:tag` inside a shell `run:` block is intentionally no longer gated
    (see REQUIREMENTS §11.3 scope note).
    """
    no_comments = "\n".join(
        line for line in "\n".join(_fold_logical_lines(text)).splitlines() if not line.lstrip().startswith("#")
    )
    violations: list[str] = list(fetch_execute_violations(no_comments))
    for match in _PIP_INSTALL_RE.finditer(no_comments):
        for pkg in _unpinned_pip_packages(match.group("rest")):
            violations.append(f"pip-installed tool not pinned to an exact version: {pkg}")
    return violations


def action_pin_violations(root: Path) -> list[str]:
    """Scan a repo's workflows + scaffold bodies for §11.3 violations.

    Real `.github/workflows/` get zizmor (`unpinned-uses`/`unpinned-images`) for action/image
    pinning. Scaffold template bodies (`wf-*.yml`, carrying `{{ aviato-ref }}` placeholders zizmor
    cannot parse) get a placeholder-aware `uses:` SHA check. Both get the fail-closed fetch-execute
    + pip checks. Seeded requirements files get the exact-pin check.
    """
    from .zizmor_scan import ZizmorUnavailable, zizmor_uses_image_violations

    root = Path(root)
    workflow_dir = root / ".github" / "workflows"
    scaffold_dir = root / "aviato" / "library" / "scaffold" / "files"
    violations: list[str] = []

    # 1. zizmor on real workflows (uses + images).
    try:
        for v in zizmor_uses_image_violations(workflow_dir):
            violations.append(f".github/workflows: {v}")
    except ZizmorUnavailable as exc:
        violations.append(f"zizmor unavailable (cannot verify action/image pins, §5.14): {exc}")

    # 2. Fetch-execute + pip checks on real workflows.
    workflow_files = sorted(p for ext in ("*.yml", "*.yaml") for p in workflow_dir.glob(ext))
    for path in workflow_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for tool in unpinned_tool_invocations(text):
            violations.append(f"{path.name}: {tool}")

    # 3. Scaffold bodies: placeholder-aware uses: + fetch + pip (zizmor can't parse templates).
    scaffold_files = sorted(p for ext in ("wf-*.yml", "wf-*.yaml") for p in scaffold_dir.glob(ext))
    for path in scaffold_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for ref in unpinned_third_party_uses(text):
            if "{{" in ref:  # scaffold placeholder, resolved at scaffold time
                continue
            violations.append(f"{path.name}: {ref}")
        for tool in unpinned_tool_invocations(text):
            violations.append(f"{path.name}: {tool}")

    # 4. Seeded requirements files (installed by CI; floors are invisible to the pip-install scan).
    for req in sorted(scaffold_dir.glob("requirements*.txt.txt")):
        for pkg in unpinned_requirements_lines(req.read_text(encoding="utf-8", errors="replace")):
            violations.append(f"{req.name}: requirement not pinned to an exact version: {pkg}")
    return violations
