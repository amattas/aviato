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


# §11.3 fetch-execute detection — built on REAL parsers (PyYAML for `run:` extraction, bashlex for the
# shell AST), not regex. Five prior text/partial-AST shapes flapped (cycle-9 enumeration, cycle-10
# checksum-word+sink, cycle-11 regex-split taint, cycle-12 "coarse", cycle-13 the first bashlex walk —
# each reopened a hole: quotes, comments, `2>&1`, option clusters, substitution, and then — once the
# lexer was right — STRUCTURAL holes the walk skipped: compound/subshell/loop bodies, redirect-target
# substitutions, command wrappers, quoted/flow `run:` keys). The convergent lesson (both engines):
# the parser must be real AND the traversal must be total. So:
#   - `run:` blocks are pulled from a real YAML parse (quoted keys / flow-style steps can't hide), with
#     a tolerant line fallback only for templated scaffold bodies that aren't valid YAML.
#   - the AST is walked GENERICALLY — every child node of every node, regardless of the attribute that
#     holds it (`parts`/`list`/`command`/`output`/heredoc/…) — so no subtree is ever skipped.
# The rule: a `curl`/`wget` is a violation if its output reaches EXECUTION —
#   (A) it pipes into a downstream pipeline element that is not a pure-data-sink command, or
#   (B) a command/process substitution carrying the fetch is EXECUTED — it is in command position
#       (`$(curl) …`) or fed to an interpreter (`bash -c "$(curl)"`, `bash <(curl)`, `bash <<<"$(curl)"`,
#       `. <(curl)`), or written into `>(interpreter)`, or
#   (C) it writes a file that a later command uses (by basename, as an arg, or via a `<` redirect) and
#       the block carries NO verify command.
# Programs are resolved through transparent wrappers (`sudo`/`env`/`timeout …`) so `sudo curl` is a
# fetch and `env jq` is a sink; a fetch in a substitution that is only CAPTURED as data (`X=$(curl)`,
# `echo "$(curl)"`) is NOT execution and is not flagged — that distinction (interpreter vs data
# context) is what keeps the gate usable. A bare fetch to stdout, a pipe into pure sinks only, and
# download → verify → use are clean. Fail CLOSED on the undecidable: a block bashlex can't parse, an
# unrecognised pipeline element. DOCUMENTED out-of-scope (best-effort gate for HONEST mistakes — NOT a
# complete control against an author obfuscating their own CI; a precise static "do fetched bytes reach
# execution" analysis over shell has an irreducible tail): heredoc-body execution
# (`bash <<EOF … $(curl) … EOF`), parameter-default obfuscation (`${X:-$(curl)}`), dynamic command
# words (`$CMD`/`sh -c "bash $f"`), and a quoted/flow `run:` key inside a TEMPLATED (non-YAML) scaffold
# body. Verify handling is BLOCK-LEVEL: any real verify command in the block vets the block's downloads,
# so a verify that runs AFTER the use, fails open (`… || true`), or covers a DIFFERENT artifact still
# vets — precise verify dataflow (order/gating/artifact-binding) is the irreducible tail and an
# order-aware attempt (cycle-13) was reverted (cycle-14) for FP-ing every verified install whose
# checksum/setup names the artifact before the verifier (`printf … tool | sha256sum -c -`). Convergent
# design; do not revert it to text matching, and do not narrow the generic descent.
_FETCH_RE = re.compile(r"\b(?:curl|wget)\b")  # cheap pre-filter only; the real check is the AST walk
_FETCH_NAMES = frozenset({"curl", "wget"})
# Pure data sinks: consume stdin and emit to stdout only — never execute stdin nor (without an explicit
# redirect) write a file. Deliberately EXCLUDES sort (`--compress-program=CMD` executes, cycle-12
# C12-9), less/more (shell escapes), awk/sed (`-f`/`-e`), xargs, tee (writes a file), and every shell.
_PURE_SINKS = frozenset({"jq", "grep", "egrep", "fgrep", "rg", "head", "tail", "cut", "tr", "nl", "wc", "cat"})
# Transparent wrappers peeled to resolve a command's real program: `sudo curl`/`env curl`/`timeout 5
# curl` are fetches, `env jq` is a sink. Resolving by program position (not "any word") also stops a
# literal `curl`/`wget` ARGUMENT (`grep curl`) being mistaken for a fetch.
_WRAPPERS = frozenset(
    {"sudo", "env", "command", "nice", "ionice", "nohup", "stdbuf", "setsid", "time", "timeout", "doas", "chronic"}
)
# Interpreters: a substitution fed to one of these is EXECUTED (vs merely captured as data). The dual of
# _PURE_SINKS for the substitution rule. `python`/`perl`/`ruby`/`node` are included conservatively.
_INTERPRETERS = frozenset(
    {"bash", "sh", "dash", "zsh", "ksh", "ash", "eval", "source", ".", "xargs",
     "python", "python2", "python3", "perl", "ruby", "node", "nodejs", "php", "pwsh", "powershell"}
)  # fmt: skip
# Shells run their FIRST positional as a script and their stdin as code; the others need an explicit
# code flag. A fetch substitution flags as executed only in a CODE position, never as a data arg to a
# script (`python report.py "$(curl)"`), so the interpreter rule stays usable (cycle-13 R4).
_SHELLS = frozenset({"bash", "sh", "dash", "zsh", "ksh", "ash"})
_CODE_FLAGS = frozenset({"-c", "-e", "-E", "--command", "--eval"})  # operand is code, not a filename
_CODE_FLAG_PREFIXES = ("-c", "-e", "-E", "--command=", "--eval=")  # a GLUED code operand: `-c"$(curl)"`
_MAX_SHELL_DEPTH = 4  # recursion guard for `bash -c '… bash -c "…" …'` nesting (cycle-15)
# Verifier commands (a verifier tool + its check/verify subcommand) are recognised as real command
# nodes only, in `_is_verifier` — a checksum word in a comment/string is dropped by the lexer, so it
# can no longer grant trust (closes cycle-12 C12-5).
# A run key anywhere (block `run:`, quoted `"run":`, or flow `{…, run: …}`) → try structural YAML
# extraction. Broad on purpose: a false trigger just enters the (robust) YAML path; the line fallback
# below handles templated bodies.
_RUN_KEY_RE = re.compile(r"""(?m)(?:^|[\s,{])['"]?run['"]?\s*:""")
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


def _collect_run_blocks(doc: object) -> list[str]:
    """Every ``run:`` scalar in a parsed-YAML workflow, found STRUCTURALLY (recurse dicts/lists). A
    real YAML parse normalises quoted keys (`"run":`), flow-mapping steps (`{run: …}`), and block
    scalars — so none can hide a `curl|bash` from the gate the way a line regex let them (cycle-13
    Group D)."""
    blocks: list[str] = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            if isinstance(key, str) and key.strip() == "run" and isinstance(value, str):
                blocks.append(value)
            else:
                blocks.extend(_collect_run_blocks(value))
    elif isinstance(doc, list):
        for item in doc:
            blocks.extend(_collect_run_blocks(item))
    return blocks


def _run_blocks(text: str) -> list[str]:
    """Extract shell ``run:`` block bodies so workflow METADATA is never analyzed as shell (C11-5).

    A real YAML parse finds every ``run:`` value structurally (quoted/flow keys, block scalars — closes
    cycle-13 Group D). Templated scaffold bodies (`{{ … }}`) are not valid YAML and fall back to the
    tolerant line extractor — which handles `run :` (space), block-scalar indicators (`|2`/`|-`/`>+`),
    and a trailing `# comment` (C12-8). Raw shell (no ``run:`` at all, e.g. a unit-test snippet) is
    returned whole."""
    if not _RUN_KEY_RE.search(text):
        return [text]
    try:
        import yaml

        doc = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — not valid YAML (templated scaffold) → line-extractor fallback
        doc = None
    if doc is not None and not isinstance(doc, str):
        blocks = _collect_run_blocks(doc)
        if blocks:
            return blocks
    # Fallback: tolerant line extractor (templated bodies, or a YAML doc with no run: scalar).
    lines = text.splitlines()
    blocks = []
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


def _children(node: object) -> list[object]:
    """Every child AST node, regardless of the attribute that holds it. bashlex stores children under
    differently-named attrs (`parts`, `list`, `command`, `output`, `heredoc`, …) and some as Python
    lists (`CompoundNode.list`). A generic descent over all node-valued attrs is the ONLY way to reach
    compound/subshell/loop bodies and redirect-target substitutions — a named-attr probe silently skips
    them and the walk fails OPEN (cycle-13 Group A)."""
    children: list[object] = []
    for value in vars(node).values():
        if getattr(value, "kind", None):
            children.append(value)
        elif isinstance(value, (list, tuple)):
            children.extend(v for v in value if getattr(v, "kind", None))
    return children


def _plain_words(node: object) -> list[str]:
    """The literal WORD tokens of a CommandNode (excludes assignments and redirect operators)."""
    return [p.word for p in getattr(node, "parts", []) if getattr(p, "kind", None) == "word"]


def _resolved_program(node: object) -> str | None:
    """The basename of a CommandNode's real PROGRAM, peeling transparent wrappers and their operands so
    `sudo curl`/`env A=1 curl`/`timeout 5 curl` resolve to `curl`. Resolving by program POSITION (vs
    matching any word) keeps `sudo curl` a fetch while a literal `curl` ARGUMENT (`grep curl`) is not."""
    if getattr(node, "kind", None) != "command":
        return None
    words = _plain_words(node)
    i = 0
    while i < len(words):
        base = _basename(words[i])
        if base not in _WRAPPERS:
            return base
        i += 1
        while i < len(words) and words[i].startswith("-"):  # skip the wrapper's own flags
            i += 1
        if base == "env":  # env VAR=val … program
            while i < len(words) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[i]):
                i += 1
        elif base == "timeout" and i < len(words) and re.fullmatch(r"[0-9]+(\.[0-9]+)?[smhd]?", words[i]):
            i += 1  # timeout DURATION program
    return None


def _is_introspection(node: object) -> bool:
    """`command -v X` / `type X` / `which X` look a program UP — they neither fetch nor execute it, so
    `command -v curl` must not read as a curl fetch (cycle-13 R4)."""
    words = _plain_words(node)
    if not words:
        return False
    prog = _basename(words[0])
    if prog == "command":
        return any(w in ("-v", "-V", "--version") for w in words)
    return prog in ("type", "which", "hash", "whereis")


def _fetch_tool(node: object) -> str | None:
    """'curl'/'wget' if this CommandNode runs one (through wrappers, cycle-13 Group B)."""
    if _is_introspection(node):
        return None
    prog = _resolved_program(node)
    if prog in _FETCH_NAMES:
        return prog
    # A wrapper whose options take ARGUMENTS (`env -u X curl`, `sudo -u root curl`) can hide the program
    # from the position-based resolve. When the command STARTS with a wrapper, fall back to any
    # curl/wget word (fail-closed). `grep curl` has no wrapper, so it is unaffected (no false fetch).
    words = _plain_words(node)
    if words and _basename(words[0]) in _WRAPPERS:
        for word in words:
            if _basename(word) in _FETCH_NAMES:
                return _basename(word)
    return None


def _is_interpreter(node: object) -> bool:
    """True if the command runs an interpreter (`bash`/`sh`/`eval`/`source`/`.`/`python`/…) — a
    substitution fed to one is EXECUTED, not merely captured as data. Resolves the PROGRAM through
    wrappers, with a wrapper-present fallback to any interpreter word (mirrors `_fetch_tool`) so
    `sudo -u root bash -c …`/`timeout -k 5s 30s bash -c …` are caught WITHOUT misreading a literal
    interpreter token in an ordinary command's args (`grep bash -e …`) as an interpreter (cycle-15)."""
    if getattr(node, "kind", None) != "command":
        return False
    if _resolved_program(node) in _INTERPRETERS:
        return True
    words = _plain_words(node)
    return bool(words) and _basename(words[0]) in _WRAPPERS and any(_basename(w) in _INTERPRETERS for w in words)


def _is_shell(node: object) -> bool:
    """True if the command runs a POSIX shell (`bash`/`sh`/…) — whose `-c` operand is itself shell, vs
    `python`/`perl`/`ruby` whose `-c`/`-e` operand is that LANGUAGE's code (never re-parsed as shell)."""
    if getattr(node, "kind", None) != "command":
        return False
    if _resolved_program(node) in _SHELLS:
        return True
    words = _plain_words(node)
    return bool(words) and _basename(words[0]) in _WRAPPERS and any(_basename(w) in _SHELLS for w in words)


def _static_code_operands(node: object) -> list[str]:
    """The LITERAL (substitution-free) string operands of a shell's `-c`/`-e` flag. These are shell to be
    recursively scanned (`bash -c 'curl | bash'`); an operand carrying a substitution is already handled
    by `_interpreter_executes_fetch`, so it is skipped here to avoid double work."""
    word_parts = [p for p in getattr(node, "parts", []) if getattr(p, "kind", None) == "word"]
    operands: list[str] = []
    for i, part in enumerate(word_parts):
        if part.word in _CODE_FLAGS and i + 1 < len(word_parts):
            nxt = word_parts[i + 1]
            has_subst = any(
                getattr(c, "kind", None) in ("commandsubstitution", "processsubstitution")
                for c in getattr(nxt, "parts", [])
            )
            if not has_subst:
                operands.append(nxt.word)
    return operands


def _subtree_has_fetch(node: object) -> bool:
    """True if any CommandNode anywhere in this node's subtree runs curl/wget — so a fetch hidden in a
    group/subshell pipeline element (`{ curl; } | bash`) is still seen as a source."""
    if _fetch_tool(node):
        return True
    return any(_subtree_has_fetch(child) for child in _children(node))


def _is_pure_sink(node: object) -> bool:
    """A downstream pipeline element is "safe" only if its resolved program is a pure-sink (`env jq`
    counts). A compound / subshell / loop, or a wrapped non-sink (`sudo bash`), is an executor."""
    return getattr(node, "kind", None) == "command" and _resolved_program(node) in _PURE_SINKS


def _word_has_fetch_subst(word: object) -> bool:
    """True if a WORD node carries a command/process substitution whose subtree runs curl/wget
    (`"$(curl)"`, `<(curl)`)."""
    return any(
        getattr(p, "kind", None) in ("commandsubstitution", "processsubstitution") and _subtree_has_fetch(p)
        for p in getattr(word, "parts", [])
    )


def _command_position_fetch_subst(node: object) -> bool:
    """True if the command-position word is a fetch substitution (`$(curl …) arg` runs the fetched
    bytes as the command)."""
    for part in getattr(node, "parts", []):
        if getattr(part, "kind", None) == "word":
            return _word_has_fetch_subst(part)  # first word is the program position
        if getattr(part, "kind", None) == "assignment":
            continue
    return False


def _interpreter_executes_fetch(node: object) -> bool:
    """True if a fetch substitution reaches an interpreter in a CODE position — the operand of `-c`/`-e`,
    an `eval`/`source` argument, a shell's first positional (`bash <(curl)`), or its stdin
    (`bash <<<"$(curl)"`, `bash < <(curl)`). A fetch passed as a DATA arg to a script
    (`python3 report.py "$(curl)"`) is not execution and is not flagged (cycle-13 R4)."""
    if not _is_interpreter(node) or _is_introspection(node):
        return False
    word_parts = [p for p in getattr(node, "parts", []) if getattr(p, "kind", None) == "word"]
    names = {_basename(p.word) for p in word_parts}
    # eval / source / . : every argument is code.
    if names & {"eval", "source", "."} and any(_word_has_fetch_subst(p) for p in word_parts):
        return True
    # a code flag carries the fetch — its SEPARATE operand (`-c "$(curl)"`) OR a GLUED operand
    # (`-c"$(curl)"`, which bashlex tokenises as one `-c$(…)` word; cycle-14 R3 fail-open).
    for i, part in enumerate(word_parts):
        if part.word in _CODE_FLAGS and i + 1 < len(word_parts) and _word_has_fetch_subst(word_parts[i + 1]):
            return True
        if part.word.startswith(_CODE_FLAG_PREFIXES) and _word_has_fetch_subst(part):
            return True
    # a shell runs its FIRST positional as a script (`bash <(curl)`); later words are its data args.
    if names & _SHELLS:
        for part in word_parts[1:]:
            if part.word.startswith("-"):
                continue
            if _word_has_fetch_subst(part):
                return True
            break
    # stdin fed to the interpreter is code (`bash <<<"$(curl)"`, `bash < <(curl)`, `xargs sh < <(curl)`).
    for part in getattr(node, "parts", []):
        if getattr(part, "kind", None) == "redirect" and getattr(part, "type", None) in ("<", "<<<"):
            out = getattr(part, "output", None)
            if out is not None and _word_has_fetch_subst(out):
                return True
    return False


def _redirects_to_interpreter_procsub(node: object) -> bool:
    """True if a `>`/`>>` redirect target of this command is a process substitution running an
    interpreter (`curl … > >(bash)`, `… | cat > >(bash)`) — the bytes are written into a shell."""
    for part in getattr(node, "parts", []):
        if getattr(part, "kind", None) == "redirect" and getattr(part, "type", None) in (">", ">>"):
            out = getattr(part, "output", None)
            for sub in getattr(out, "parts", []):
                if getattr(sub, "kind", None) == "processsubstitution" and _is_interpreter(
                    getattr(sub, "command", None)
                ):
                    return True
    return False


def _input_redirect_files(node: object) -> set[str]:
    """Filenames a command reads via a `<`/`0<` redirect (`bash < f` USES f)."""
    files: set[str] = set()
    for part in getattr(node, "parts", []):
        if getattr(part, "kind", None) == "redirect" and getattr(part, "type", None) in ("<", "0<"):
            out = getattr(part, "output", None)
            if out is not None and getattr(out, "kind", None) == "word":
                files.add(out.word)
    return files


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


def _fetch_output_files(node: object, tool: str) -> set[str]:
    """Files a curl/wget command writes (a later use of one is "used unverified fetched bytes").

    Parses the bounded, stable curl/wget output grammar — `-o`/`--output`(`=`)`, the curl `-O`/
    `--remote-name` and clustered/glued `-fsSLo FILE`/`-oFILE` forms, the wget `-O`/`-OFILE`/
    `--output-document` forms, `--output-dir`/`-P`/`--directory-prefix` path prefixes, the wget
    default-basename download, and any `>`/`>>` redirect target. Over-detecting a written file is
    fail-closed; under-detecting (cycle-13 Group C: `wget -O`, glued `-o`, `--output-dir`) is the bug
    this closes. Empty set ⇒ the fetch streams to stdout."""
    words = _plain_words(node)
    files: set[str] = set()
    files |= _redirect_files(node)
    urls = [w for w in words if "://" in w]
    out_dir: str | None = None
    i = 0
    while i < len(words):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w in ("--output-dir", "-P", "--directory-prefix") and nxt is not None:
            out_dir = nxt
            i += 2
            continue
        if w.startswith("--output-dir=") or w.startswith("--directory-prefix="):
            out_dir = w.split("=", 1)[1]
        elif w in ("-o", "--output") and nxt is not None:  # curl output; wget -o is a logfile → fail-closed
            files.add(nxt.lstrip("="))
            i += 2
            continue
        elif w.startswith("--output="):
            files.add(w.split("=", 1)[1])
        elif tool == "wget" and w in ("-O", "--output-document") and nxt is not None:
            if nxt != "-":
                files.add(nxt.lstrip("="))
            i += 2
            continue
        elif tool == "wget" and w.startswith("--output-document="):
            val = w.split("=", 1)[1]
            if val != "-":
                files.add(val)
        elif tool == "wget" and re.fullmatch(r"-O.+", w):  # glued wget -OFILE / -O=FILE
            val = w[2:].lstrip("=")
            if val != "-":
                files.add(val)
        elif tool == "curl" and w in ("-O", "--remote-name", "--remote-name-all"):
            files.update(_basename(u) for u in urls)
        elif tool == "curl" and re.fullmatch(r"-[a-zA-Z]*o", w) and nxt is not None:  # cluster -…o FILE
            files.add(nxt.lstrip("="))
            i += 2
            continue
        elif tool == "curl" and not w.startswith("--") and re.fullmatch(r"-[a-zA-Z]*o=?.+", w):  # glued -oFILE
            files.add(re.sub(r"^-[a-zA-Z]*o=?", "", w))
        elif tool == "curl" and re.fullmatch(r"-[a-zA-Z]*O[a-zA-Z]*", w):  # cluster containing O
            files.update(_basename(u) for u in urls)
        i += 1
    # wget writes the remote basename by default unless it streams to stdout.
    if tool == "wget" and not files:
        streams = any(
            w in ("-O-", "-qO-", "--output-document=-") or (w in ("-O", "--output-document") and "-" in words)
            for w in words
        ) or any("/dev/stdout" in w for w in words)
        if not streams:
            files.update(_basename(u) for u in urls)
    if out_dir:  # a path prefix yields both the bare basename and the prefixed path
        prefix = out_dir.rstrip("/")
        files |= {f"{prefix}/{_basename(f)}" for f in list(files)}
        files |= {f"{prefix}/{_basename(u)}" for u in urls}
    return files


class _FetchWalk:
    """Walks a bashlex AST collecting what's needed to decide §11.3 fetch-execute violations."""

    def __init__(self, depth: int = 0) -> None:
        self.violations: list[str] = []
        self.downloads: set[str] = set()  # files holding unverified fetched bytes
        self.has_verifier: bool = False  # a real verify command anywhere in the block → downloads vetted
        self.used: set[str] = set()  # words used by non-fetch, non-verifier commands
        self.depth: int = depth  # recursion depth into shell `-c` strings (cycle-15)

    def walk(self, node: object) -> None:
        kind = getattr(node, "kind", None)
        if kind == "pipeline":
            self._pipeline(node)
        elif kind == "command":
            self._command(node)
        # GENERIC descent — every child node, whatever attribute holds it (including the inner command
        # of a substitution, walked here so its own fetches are still collected). Never narrow this to
        # named attributes: that is exactly how cycle-13 Group A failed open (compound/subshell/loop
        # bodies and redirect-target substitutions were skipped). Whether a substitution EXECUTES is
        # decided by its enclosing command in `_command`, not by the bare fact of being a substitution.
        for child in _children(node):
            self.walk(child)

    def _pipeline(self, node: object) -> None:
        elements = [p for p in node.parts if getattr(p, "kind", None) != "pipe"]
        for idx, element in enumerate(elements):
            # (A) a fetch's bytes flow into a downstream element. Safe only if EVERY downstream element
            # is a pure-sink command — a stream cannot be checksum-verified mid-flight, so a verifier
            # elsewhere never excuses it (C12-1), and a compound / subshell / wrapped non-sink counts as
            # an executor (cycle-13 Group A/B).
            if _subtree_has_fetch(element) and any(not _is_pure_sink(d) for d in elements[idx + 1 :]):
                self.violations.append("fetch piped into a non-data-sink command")
        if any(_subtree_has_fetch(e) for e in elements):
            for element in elements:
                if getattr(element, "kind", None) != "command":
                    continue
                if _redirects_to_interpreter_procsub(element):  # `curl | cat > >(bash)`
                    self.violations.append("fetch written into a process substitution running a shell")
                # Files written ANYWHERE in a fetch-bearing pipeline (`curl | cat > f`) hold fetched bytes.
                tool = _fetch_tool(element)
                self.downloads |= _fetch_output_files(element, tool) if tool else _redirect_files(element)

    def _command(self, node: object) -> None:
        tool = _fetch_tool(node)
        if tool:
            if _redirects_to_interpreter_procsub(node):
                # `curl … > >(bash)` — the fetch's bytes are written straight into a shell. Execution.
                self.violations.append("fetch written into a process substitution running a shell")
            self.downloads |= _fetch_output_files(node, tool)
            return
        if _is_verifier(node):
            # A real verify COMMAND (not a comment/string — the lexer dropped those) vets the block's
            # DOWNLOADS. It does NOT vet a streamed fetch (handled above). Verify handling is deliberately
            # BLOCK-LEVEL, not order/gating/artifact aware — an order-aware attempt (cycle-13 R5) was
            # reverted (cycle-14 R1) because it false-positived every legitimate verified install whose
            # checksum names the artifact (`printf "%s  %s" "$SHA" tool | sha256sum -c -`) or whose setup
            # touches it (`chmod +x tool`) before the verifier ran. The cost: a verify that runs AFTER
            # the use, fails open (`|| true`), or covers a DIFFERENT artifact still vets — documented
            # out-of-scope for this honest-mistake gate (precise verify dataflow is the irreducible tail).
            self.has_verifier = True
            return
        # (B) a fetch substitution that is EXECUTED — run as the command (`$(curl) …`) or fed to an
        # interpreter (`bash -c "$(curl)"`, `bash <(curl)`, `bash <<<"$(curl)"`). A substitution merely
        # CAPTURED as data (`X=$(curl)`, `echo "$(curl)"`) is not flagged — that is what keeps the gate
        # usable on the dominant "fetch a value" pattern.
        if _command_position_fetch_subst(node):
            self.violations.append("fetch substitution run as a command")
        elif _interpreter_executes_fetch(node):
            self.violations.append("fetch substitution executed by an interpreter")
        # cycle-15: a shell's static `-c`/`-e` STRING operand is itself shell — recursively scan it so
        # `bash -c 'curl | bash'` (literal code, not a substitution) is not a fail-open. Depth-guarded.
        if self.depth < _MAX_SHELL_DEPTH and _is_shell(node):
            for operand in _static_code_operands(node):
                for reason in _scan_block(operand, self.depth + 1):
                    self.violations.append(f"shell -c string: {reason}")
        self.used |= set(_plain_words(node)) | _input_redirect_files(node)  # `bash < f` USES f


def _redirect_files(node: object) -> set[str]:
    files: set[str] = set()
    for part in getattr(node, "parts", []):
        if getattr(part, "kind", None) == "redirect" and getattr(part, "type", None) in (">", ">>"):
            out = getattr(part, "output", None)
            if out is not None and getattr(out, "kind", None) == "word" and out.word != "/dev/null":
                files.add(out.word)
    return files


def _file_match(download: str, word: str) -> bool:
    """Whether a used `word` references a downloaded file. Normalises a leading `./` and matches on
    basename ONLY when one side carries no directory — so `./install.sh` matches a downloaded
    `install.sh`, but `/tmp/data.json` and `./fixtures/data.json` (different dirs) do NOT collide."""
    d = download[2:] if download.startswith("./") else download
    u = word[2:] if word.startswith("./") else word
    return d == u or ("/" not in d and _basename(u) == d) or ("/" not in u and _basename(d) == u)


def _scan_block(block: str, depth: int = 0) -> list[str]:
    """Parse one shell block and return its fetch-execute violation reasons. Recursive: a shell's static
    `-c`/`-e` string operand IS more shell, so it is scanned at ``depth+1`` (cycle-15: `bash -c 'curl |
    bash'` is a literal code string, not a substitution). A block that mentions curl/wget but bashlex
    cannot parse fails CLOSED."""
    import bashlex

    if not _FETCH_RE.search(block):
        return []
    try:
        trees = bashlex.parse(block)
    except Exception:  # noqa: BLE001 — ANY parse failure (templated/garbled) → cannot prove safe
        return [f"(unparsed block): {block.strip()[:80]}"]
    walk = _FetchWalk(depth)
    for tree in trees:
        walk.walk(tree)
    reasons = list(walk.violations)
    # (C) a downloaded file used by a later command, with no verify command in the block. `./install.sh`
    # matches a downloaded `install.sh`, but unrelated paths sharing a basename (`/tmp/data.json` vs
    # `./fixtures/data.json`) do not collide.
    if not walk.has_verifier:
        unverified = sorted(d for d in walk.downloads if any(_file_match(d, word) for word in walk.used))
        if unverified:
            reasons.append(f"unverified downloaded file used: {unverified}")
    return reasons


def fetch_execute_violations(text: str) -> list[str]:
    """Fail-closed §11.3 fetch-execute check over a real shell AST (design contract above).

    For each ``run:`` block: parse it with bashlex and walk the AST. A `curl`/`wget` is flagged when
    its output reaches execution (non-sink pipe / executed substitution / a downloaded file used
    unverified / a shell `-c` string that itself fetch-executes)."""
    violations: list[str] = []
    for block in _run_blocks(text):
        reasons = _scan_block(block, 0)
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
