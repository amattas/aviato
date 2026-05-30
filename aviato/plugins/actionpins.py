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


# §11.3 fetch-execute detection — built on a REAL shell parser (bashlex), not regex. Four prior
# regex/string shapes flapped (cycle-9 enumeration, cycle-10 checksum-word+sink, cycle-11 regex-split
# taint, cycle-12 "coarse" — each reopened a shell-grammar hole: quotes, comments, `2>&1`, option
# clusters, substitution). The lesson (both review engines): you cannot decide "do fetched bytes reach
# execution" by matching shell text. bashlex tokenizes correctly — comments are dropped, `2>&1` is a
# redirect not a separator, `-fsSLo` is one word, `$(…)`/`<(…)` are real nodes — so the decision is a
# clean AST walk. The rule: a `curl`/`wget` is a violation if its output can reach execution —
#   (A) it sits inside a command/process substitution (its bytes become a command/arg), or
#   (B) it pipes into anything that is not a pure data sink, or
#   (C) it writes a file that a later command uses and no verify command covers that file.
# A bare fetch to stdout, or a pipe into pure data sinks only, is clean; download → verify → use is
# clean. Undecidable cases (a dynamic command word like `$CMD`, a fetch in a block bashlex can't parse)
# fail CLOSED. This is the convergent design; do not revert it to text matching.
_FETCH_RE = re.compile(r"\b(?:curl|wget)\b")  # cheap pre-filter only; the real check is the AST walk
_FETCH_NAMES = frozenset({"curl", "wget"})
# Pure data sinks: consume stdin and emit to stdout only — never execute stdin nor (without an explicit
# redirect) write a file. Deliberately EXCLUDES sort (`--compress-program=CMD` executes, cycle-12
# C12-9), less/more (shell escapes), awk/sed (`-f`/`-e`), xargs, tee (writes a file), and every shell.
_PURE_SINKS = frozenset({"jq", "grep", "egrep", "fgrep", "rg", "head", "tail", "cut", "tr", "nl", "wc", "cat"})
# Verifier commands (a verifier tool + its check/verify subcommand) are recognised as real command
# nodes only, in `_is_verifier` — a checksum word in a comment/string is dropped by the lexer, so it
# can no longer grant trust (closes cycle-12 C12-5).
_RUN_KEY_RE = re.compile(r"(?m)^\s*-?\s*run\s*:")
_RUN_LINE_RE = re.compile(r"^(?P<indent>\s*)-?\s*run\s*:\s*(?P<rest>.*)$")
_SCALAR_RE = re.compile(r"^[|>][+-]?[0-9]*$")  # block-scalar indicator: |, >, |-, |2, >+2, … (C12-8)


def _fold_logical_lines(text: str) -> list[str]:
    """Fold `\\`-newline continuations and split-pipe scalars into logical lines. Folding only JOINS,
    so it can add flags, never remove them (fail-closed safe). Used by the pip-pin scan only."""
    text = re.sub(r"\\\n[ \t]*", " ", text)
    text = re.sub(r"\|[ \t]*\n[ \t]*", "| ", text)
    text = re.sub(r"\n[ \t]*\|", " |", text)
    return text.splitlines()


def _basename(token: str) -> str:
    return token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def _run_blocks(text: str) -> list[str]:
    """Extract shell ``run:`` block bodies so workflow METADATA is never analyzed as shell (C11-5).
    Handles `run :` (space), block-scalar indicators (`|2`/`|-`/`>+`), and a trailing `# comment` on
    the indicator line (C12-8). Tolerant of templated (`{{ … }}`) bodies. No ``run:`` → one raw block."""
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
        rest = re.sub(r"\s+#.*$", "", match.group("rest")).strip()  # drop a trailing YAML comment
        if _SCALAR_RE.match(rest):
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
            blocks.append(match.group("rest"))  # inline run:
            i += 1
    return blocks


def _node_words(node: object) -> list[str]:
    """Literal command-line words of a CommandNode, including `>`/`>>` redirect targets."""
    words: list[str] = []
    for part in getattr(node, "parts", []):
        kind = getattr(part, "kind", None)
        if kind == "word":
            words.append(part.word)
        elif kind == "redirect":
            out = getattr(part, "output", None)
            if out is not None and getattr(out, "kind", None) == "word":
                words.append(out.word)
    return words


def _command_name(node: object) -> str | None:
    for part in getattr(node, "parts", []):
        if getattr(part, "kind", None) == "word":
            return _basename(part.word)
    return None


def _is_verifier(node: object) -> bool:
    """A real verify command: a verifier tool with its check/verify subcommand or flag."""
    words = _node_words(node)
    if not words:
        return False
    name = _basename(words[0])
    rest = words[1:]
    if name in {"sha256sum", "sha512sum", "sha1sum", "shasum", "b2sum", "md5sum"}:
        return any(w in ("-c", "--check") for w in rest)
    if name == "cosign":
        return any(w in ("verify", "verify-blob") for w in rest)
    if name == "gpg":
        return any(w in ("--verify", "--decrypt") for w in rest)
    if name == "minisign":
        return "-V" in rest
    return False


def _fetch_output_files(node: object) -> set[str]:
    """Files a curl/wget command writes (so later use of them is "used unverified fetched bytes").

    Parses the KNOWN output options of curl/wget (bounded + stable, unlike whole-line regex) plus any
    `>`/`>>` redirect target. Empty set ⇒ the fetch streams to stdout (a bare/piped fetch)."""
    parts = getattr(node, "parts", [])
    words = [p.word for p in parts if getattr(p, "kind", None) == "word"]
    if not words:
        return set()
    tool = _basename(words[0])
    files: set[str] = set()
    # `>`/`>>` redirect targets are downloads regardless of tool.
    for part in parts:
        if getattr(part, "kind", None) == "redirect" and getattr(part, "type", None) in (">", ">>"):
            out = getattr(part, "output", None)
            if out is not None and getattr(out, "kind", None) == "word" and out.word not in ("/dev/null",):
                files.add(out.word)
    urls = [w for w in words[1:] if "://" in w]
    args = words[1:]
    i = 0
    while i < len(args):
        w = args[i]
        if w in ("-o", "--output") and i + 1 < len(args):
            files.add(args[i + 1])
            i += 2
            continue
        if w.startswith("--output="):
            files.add(w.split("=", 1)[1])
        elif w.startswith("--output-document="):  # wget
            val = w.split("=", 1)[1]
            if val != "-":
                files.add(val)
        elif w == "--output-document" and i + 1 < len(args):
            if args[i + 1] != "-":
                files.add(args[i + 1])
            i += 2
            continue
        elif w in ("--remote-name", "--remote-name-all", "-O") and tool == "curl":
            files.update(_basename(u) for u in urls)  # curl -O / --remote-name → remote basename
        elif tool == "curl" and re.fullmatch(r"-[a-zA-Z]*o", w):  # short-option cluster ending in `o`
            if i + 1 < len(args):
                files.add(args[i + 1])
                i += 2
                continue
        elif tool == "curl" and re.fullmatch(r"-[a-zA-Z]*O[a-zA-Z]*", w):  # cluster containing `O`
            files.update(_basename(u) for u in urls)
        i += 1
    # wget writes a file by default (remote basename) unless it streams to stdout.
    if tool == "wget" and not files:
        stdout = any(
            w in ("-O-", "-qO-", "--output-document=-") or (w in ("-O", "--output-document") and "-" in args)
            for w in args
        ) or any("/dev/stdout" in w for w in args)
        if not stdout:
            files.update(_basename(u) for u in urls)
    return files


class _FetchWalk:
    """Walks a bashlex AST collecting what's needed to decide §11.3 fetch-execute violations."""

    def __init__(self) -> None:
        self.violations: list[str] = []
        self.downloads: set[str] = set()  # files holding unverified fetched bytes
        self.has_verifier: bool = False  # a real verify command anywhere → downloads are vetted
        self.used: set[str] = set()  # words used by non-fetch, non-verifier commands

    def walk(self, node: object, in_subst: bool) -> None:
        kind = getattr(node, "kind", None)
        if kind == "pipeline":
            self._pipeline(node)
            for part in node.parts:
                self.walk(part, in_subst)
            return
        if kind == "command":
            self._command(node, in_subst)
            for part in getattr(node, "parts", []):
                self.walk(part, in_subst)  # words may carry substitutions
            return
        if kind in ("commandsubstitution", "processsubstitution"):
            cmd = getattr(node, "command", None)
            if cmd is not None:
                self.walk(cmd, True)
            return
        if kind == "word":
            for part in getattr(node, "parts", []):
                self.walk(part, in_subst)
            return
        for part in getattr(node, "parts", []):  # list/compound/etc.
            self.walk(part, in_subst)
        for attr in ("list", "command"):
            child = getattr(node, attr, None)
            if child is not None and getattr(child, "kind", None):
                self.walk(child, in_subst)

    def _pipeline(self, node: object) -> None:
        commands = [p for p in node.parts if getattr(p, "kind", None) == "command"]
        pipe_has_fetch = any(_command_name(c) in _FETCH_NAMES for c in commands)
        for idx, cmd in enumerate(commands):
            if _command_name(cmd) in _FETCH_NAMES:
                downstream = commands[idx + 1 :]
                if any(_command_name(d) not in _PURE_SINKS for d in downstream):
                    # (B) fetch streams into something that is not a pure data sink — a stream cannot
                    # be checksum-verified mid-flight, so a verifier elsewhere never excuses it (C12-1).
                    self.violations.append("fetch piped into a non-data-sink command")
        if pipe_has_fetch:
            # Files written ANYWHERE in a fetch-bearing pipeline (`curl | cat > f`) hold fetched bytes.
            for cmd in commands:
                if _command_name(cmd) in _FETCH_NAMES:
                    self.downloads |= _fetch_output_files(cmd)
                else:
                    self.downloads |= _redirect_files(cmd)

    def _command(self, node: object, in_subst: bool) -> None:
        name = _command_name(node)
        if name in _FETCH_NAMES:
            if in_subst:
                # (A) a fetch inside `$(…)`/`<(…)`/`>(…)` — its bytes become a command/arg/file; a
                # stream into a command position cannot be verified, so this always flags.
                self.violations.append("fetch inside a command/process substitution")
            self.downloads |= _fetch_output_files(node)
            return
        if _is_verifier(node):
            # A real verify COMMAND (not a comment/string — the lexer dropped those) vets DOWNLOADS in
            # this block. It does NOT vet streamed fetches (handled above). Binding the verifier to the
            # exact artifact is not attempted: a deliberately-fake verify (`sha256sum -c /dev/null`) on
            # a download is a documented out-of-scope evasion — same class as a dynamic command word —
            # because this is an honest-mistake gate, not a defense against a self-attacking author.
            self.has_verifier = True
            return
        self.used |= set(_node_words(node))


def _redirect_files(node: object) -> set[str]:
    files: set[str] = set()
    for part in getattr(node, "parts", []):
        if getattr(part, "kind", None) == "redirect" and getattr(part, "type", None) in (">", ">>"):
            out = getattr(part, "output", None)
            if out is not None and getattr(out, "kind", None) == "word" and out.word != "/dev/null":
                files.add(out.word)
    return files


def fetch_execute_violations(text: str) -> list[str]:
    """Fail-closed §11.3 fetch-execute check over a real shell AST (design contract above).

    For each ``run:`` block: parse it with bashlex and walk the AST. A `curl`/`wget` is flagged when
    its output can reach execution (substitution / non-sink pipe / a downloaded file used unverified).
    A block bashlex cannot parse but that mentions curl/wget fails CLOSED (flagged)."""
    import bashlex

    violations: list[str] = []
    for block in _run_blocks(text):
        if not _FETCH_RE.search(block):
            continue
        try:
            trees = bashlex.parse(block)
        except Exception:  # noqa: BLE001 — ANY parse failure (templated/garbled) → cannot prove safe
            # Unparseable but it mentions curl/wget → fail closed.
            violations.append(f"fetch-and-execute without checksum (unparsed block): {block.strip()[:80]}")
            continue
        walk = _FetchWalk()
        for tree in trees:
            walk.walk(tree, False)
        reasons = list(walk.violations)
        if not walk.has_verifier and (walk.downloads & walk.used):
            # (C) a downloaded file is used by a later command and the block has no verify command.
            reasons.append(f"unverified downloaded file used: {sorted(walk.downloads & walk.used)}")
        if reasons:
            violations.append(f"fetch-and-execute without checksum: {reasons[0]}")
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
