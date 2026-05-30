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


# §11.3 fetch-execute detection — DELIBERATELY COARSE, fail-closed, FROZEN. This is a LINT, not a
# sandbox. Three prior shapes flapped: interpreter enumeration (fail-open on unknown executors,
# cycle-9 R9-1..R9-5), checksum-word + sink allowlist (fail-open on comments/chaining, cycle-10
# R10-1/R10-2), and regex-split taint (fail-open on `2>&1`/quotes/`-fsSLo`/YAML-as-shell, cycle-11
# C11-1..C11-9). The lesson (both review engines): you cannot decide "do fetched bytes reach
# execution" by regex-splitting shell — every refinement opens a new shell-grammar hole. So we STOP
# trying to be precise. The rule, over each YAML `run:` block: an unverified `curl`/`wget` is a
# violation UNLESS the block carries a real verify command, and the fetch is a *trivial safe shape* —
# a bare fetch to stdout, or a pipe into ONLY pure data sinks. Anything else (a pipe to a non-sink, a
# substitution, any command sequencing on the line, ANY download-to-a-file) is flagged. We accept the
# resulting false positives (e.g. `curl … | jq && echo` flags) as the cost of a decidable, stable
# gate — and we do NOT keep refining it. DO NOT add executor names, parse quotes, or chase edge cases.
_FETCH_RE = re.compile(r"\b(?:curl|wget)\b")
# Pure data sinks: consume stdin, emit to stdout only. A fetch piped into ONLY these is data handling.
_PURE_SINKS = frozenset(
    {"jq", "grep", "egrep", "fgrep", "rg", "head", "tail", "sort", "uniq", "wc", "cut", "tr", "less", "more", "nl"}
)
# A real verify COMMAND anywhere in the block grants block-level trust (download → verify → use). This
# is intentionally LOOSE — binding the verifier to the exact artifact needs a shell parser, which is
# the precision we are deliberately forgoing (a stray/unrelated verify clearing trust is a documented,
# accepted limitation of a coarse lint; an operator who checksums the wrong file has a footgun, not an
# attacker). A bare WORD does not match — the verb + check mode is required (closes cycle-10 R10-1).
_VERIFY_RE = re.compile(
    r"\b(?:sha(?:1|256|512)sum|shasum|b2sum|md5sum)\b[^\n]*?(?:\s-c\b|\s--check\b)"
    r"|\bcosign\s+verify(?:-blob)?\b"
    r"|\bgpg\b[^\n]*?\s--(?:verify|decrypt)\b"
    r"|\bminisign\b[^\n]*?\s-V\b"
)
# Substitution / sequencing / file-write signals — ANY of these on a fetch line means "not a trivial
# safe shape" → flag. Presence checks only (no splitting → immune to `2>&1`, quoted operators, etc.).
_SUBST_RE = re.compile(r"<\(|>\(|\$\(|`")
_SEQ_RE = re.compile(r"&&|\|\||;|&")
_REDIR_FILE_RE = re.compile(r">>?\s*(?!/dev/null\b|&)")  # `>`/`>>` to a real file (not /dev/null, not >&)
_CURL_OUT_RE = re.compile(r"(?:^|\s)(?:-o|-O|--output)(?:[=\s]|$)")
# wget writes a FILE by default; it streams to stdout only with an explicit `-O-`/`-qO-`/… form.
_WGET_STDOUT_RE = re.compile(r"-O\s*-(?:\s|$)|-O\s*/dev/stdout|-qO-|--output-document\s*=?\s*-")
_RUN_KEY_RE = re.compile(r"(?m)^\s*-?\s*run:")
_RUN_LINE_RE = re.compile(r"^(?P<indent>\s*)-?\s*run:\s*(?P<rest>.*)$")
_BLOCK_SCALAR = {"|", ">", "|-", ">-", "|+", ">+"}


def _fold_logical_lines(text: str) -> list[str]:
    """Fold `\\`-newline continuations and split-pipe scalars into logical lines. Folding only JOINS,
    so it can add flags, never remove them (fail-closed safe; closes the cycle-9 R9-2 fold cases)."""
    text = re.sub(r"\\\n[ \t]*", " ", text)  # shell line-continuation
    text = re.sub(r"\|[ \t]*\n[ \t]*", "| ", text)  # pipe at EOL → join with next
    text = re.sub(r"\n[ \t]*\|", " |", text)  # pipe leads next line → join with prev
    return text.splitlines()


def _basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _run_blocks(text: str) -> list[str]:
    """Extract shell ``run:`` block bodies so workflow METADATA is never analyzed as shell (cycle-11
    C11-5). Tolerant of templated (`{{ … }}`) bodies — line/indentation based, not a YAML parse. If
    the text has no ``run:`` marker it is treated as one raw shell block (so a bare snippet works)."""
    if not _RUN_KEY_RE.search(text):
        return [text]
    lines = text.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        match = _RUN_LINE_RE.match(lines[i])
        if not match:
            i += 1
            continue
        rest = match.group("rest").strip()
        if rest in _BLOCK_SCALAR:
            base = len(match.group("indent"))
            body: list[str] = []
            i += 1
            while i < len(lines):
                line = lines[i]
                if line.strip() and (len(line) - len(line.lstrip())) <= base:
                    break  # dedent ends the block scalar
                body.append(line)
                i += 1
            blocks.append("\n".join(body))
        else:
            blocks.append(rest)  # inline run:
            i += 1
    return blocks


def _fetch_line_is_trivially_safe(line: str) -> bool:
    """A fetch line is safe ONLY as a bare fetch to stdout or a pipe into pure data sinks — no
    substitution, no command sequencing, and no download-to-a-file. Presence checks (not splitting),
    so `curl … 2>&1 | bash` (the `&` is sequencing) and quoted operators are caught, not evaded."""
    if _SUBST_RE.search(line) or _SEQ_RE.search(line) or _REDIR_FILE_RE.search(line):
        return False
    if re.search(r"\bcurl\b", line) and _CURL_OUT_RE.search(line):
        return False  # curl -o/-O/--output writes a file
    if re.search(r"\bwget\b", line) and not _WGET_STDOUT_RE.search(line):
        return False  # wget writes a file unless explicitly streaming to stdout
    for segment in line.split("|")[1:]:  # any pipe target must be a pure data sink
        tokens = segment.split()
        if not tokens or _basename(tokens[0]) not in _PURE_SINKS:
            return False
    return True


def fetch_execute_violations(text: str) -> list[str]:
    """Coarse, fail-closed §11.3 fetch-execute check (design contract in the module comment above).

    Per YAML ``run:`` block: if the block contains a `curl`/`wget` and NO real verify command, every
    fetch line must be a trivial safe shape (bare fetch to stdout, or a pipe into pure data sinks) —
    otherwise the block is flagged. Deliberately coarse and FROZEN: it accepts false positives rather
    than chase shell-grammar edge cases, because a stable lint beats another fail-open detector.
    """
    violations: list[str] = []
    for block in _run_blocks(text):
        if not _FETCH_RE.search(block):
            continue
        if _VERIFY_RE.search(block):
            continue  # download → verify → use (block-level trust; see _VERIFY_RE comment)
        for line in _fold_logical_lines(block):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if _FETCH_RE.search(line) and not _fetch_line_is_trivially_safe(line):
                violations.append(f"fetch-and-execute without checksum: {stripped}")
                break
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
    # fetch_execute_violations takes RAW text — it extracts `run:` blocks itself, so we must NOT
    # pre-fold (folding would join the `run: |` block-scalar marker into its first body line).
    violations: list[str] = list(fetch_execute_violations(text))
    # The pip scan is line-oriented and fine on folded, comment-stripped text.
    folded = "\n".join(_fold_logical_lines(text))
    no_comments = "\n".join(line for line in folded.splitlines() if not line.lstrip().startswith("#"))
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
