from __future__ import annotations

import re
import shlex
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
# R2-2-DOCKER: a digest pin must be a full 64-hex sha256, not merely the substring `@sha256:`
# (a truncated/typo'd digest must not pass as "pinned").
_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}\b")


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


# §11.3 covers shell-fetched tools/images too, not just `uses:` refs. Two well-defined
# anti-patterns are detected: a `docker run`/`docker pull` image without an `@sha256:` digest, and
# a remote artifact fetched and piped straight into a shell/extractor (no checksum gate).
# CX#7: match BOTH run and pull so `aviato validate` agrees with the in-CI reusable-common-lint
# gate (which already scans `docker (run|pull)`) — an unpinned `docker pull alpine:3.19` is just as
# much a mutable-image supply-chain risk as `docker run`. R2-2-DOCKER: cover `docker image pull`
# and `docker container run`. R3-1-DOCKERX: enumerate ONLY the valid forms — the earlier
# `(?:image|container)?\s+(?:run|pull)` cross-product also matched the nonexistent `docker image run`
# / `docker container pull`, needlessly widening the prose surface.
_DOCKER_RUN_RE = re.compile(r"\bdocker\s+(?:run|pull|image\s+pull|container\s+run)\b(?P<rest>[^\n]*)")
# §11.3 fetch-and-execute detection. STRUCTURAL: tokenize each pipe segment (shlex), strip wrappers
# + their flags + inline `VAR=val` assignments, then ask "is the remaining command an interpreter?"
# against a CLOSED set. Replaces a 5-cycle regex flap (DA/EA/FA/GB/HB each found new wrapper or
# flag forms the prior regex didn't cover): with this shape, adding a new wrapper or interpreter
# is a one-line list edit, not a regex restructure with backtracking implications. Open-ended
# enumeration of shell idioms (`sudo -u user`, `/usr/bin/env`, `nice -n 10`, `timeout 30`, etc.)
# becomes a tokenize-then-classify problem the matcher handles uniformly. R5-1-FP (substring
# matches like `node-gyp`/`python-foo`) is structurally impossible — we compare against a token,
# not bytes. R2-2-SC2 (fetch-to-file-then-execute) stays out of scope as before; the high-signal
# pipe form is the deliberate scope.
_FETCH_CMD_RE = re.compile(r"\b(?:curl|wget)\b")
# Closed sets: a new wrapper or interpreter convention is a one-line list edit. The lists are
# bigger than they look — POSIX shells, shell BUILTINS that execute stdin (source/eval/sh -c),
# scripting languages run on real CI (lua/tclsh/R/julia/osascript/awk -f -/m4/groovy/swift/jjs),
# and BSD/Alpine variants (csh/tcsh/mksh). R8-6/R8-10/R8-13 catch-up edits below.
_INTERPRETERS: frozenset[str] = frozenset(
    {
        # POSIX shells
        "sh",
        "bash",
        "dash",
        "zsh",
        "ksh",
        "fish",
        "csh",
        "tcsh",
        "mksh",
        # shell builtins that execute stdin / piped content. `.` is bash/POSIX's source builtin —
        # `curl x | . /dev/stdin` is the canonical "run remote script as if inlined" pattern, and
        # without the entry `. /dev/stdin` would slip past the first-command check.
        "source",
        "eval",
        ".",
        # JS/Java/.NET runtimes
        "node",
        "nodejs",
        "pwsh",
        "jjs",
        "groovy",
        "swift",
        # scripting languages
        "ruby",
        "perl",
        "php",
        "lua",
        "tclsh",
        "julia",
        # data/text processors that can execute a fetched program (`-f -`)
        "awk",
        "gawk",
        "mawk",
        "sed",
        "m4",
        # macOS scripting
        "osascript",
        # R variants
        "r",
        "rscript",
        # tar (legitimately extracts a fetched archive without a checksum gate)
        "tar",
    }
)
# Python interpreter family: `python`, `python3`, `python3.11`, etc. Matched case-sensitive
# after stripping path — only the bare-or-versioned `python` name is real; `python-foo` is a
# different command (R5-1-FP).
_PYTHON_INTERP_RE = re.compile(r"^python[0-9.]*$")
# Privilege/environment/lifecycle launchers that prefix a command with options before invoking
# it. Each new launcher is a one-line addition. The matcher consumes a run of these uniformly.
_FETCH_WRAPPERS_SET: frozenset[str] = frozenset(
    {
        # privilege wrappers (sudo + alternatives)
        "sudo",
        "doas",
        "su",
        "sg",
        "runuser",
        "runas",
        "systemd-run",
        "capsh",
        # environment / chdir / chroot wrappers
        "env",
        "command",
        "exec",
        "chroot",
        # priority/scheduling wrappers
        "nice",
        "nohup",
        "time",
        "taskset",
        "chrt",
        "ionice",
        # session/lifecycle wrappers
        "setsid",
        "stdbuf",
        "unshare",
        "setpriv",
        "timeout",
        "flock",
        # sandboxes (they execute the wrapped command, just under restrictions)
        "firejail",
        "bwrap",
        # tool runners
        "watch",
        "parallel",
        # tracing/profiling wrappers (they execute the wrapped command verbatim)
        "strace",
        "ltrace",
        "eatmydata",
        # language tool runners
        "pipenv",
        "poetry",
        # busybox: subcommand-style launcher (`busybox sh`) — its first arg IS the executed cmd
        "busybox",
    }
)
_INLINE_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_TIMEOUT_DURATION_RE = re.compile(r"^\d+[smhd]?$")
# Wrappers whose FIRST positional argument is a non-command operand (a duration, group name,
# lock-path, chroot-path, etc.) — that positional must be consumed before the next token is
# treated as the command (R8-3-WRAPPERS for sg/flock/chroot; existing for timeout). The handling
# is uniform: pop one non-dash non-VAR=val non-interpreter token after the wrapper, then proceed.
_WRAPPERS_WITH_POSITIONAL_ARG: frozenset[str] = frozenset({"timeout", "sg", "flock", "chroot"})
# Language tool runners that gate the executed command behind a literal `run` subcommand
# (`poetry run cmd`, `pipenv run cmd`). These wrappers only execute the FOLLOWING command when
# the next token is the literal `run` — `poetry add bash` does NOT execute bash, it adds a
# dependency named bash. Consume the `run` subcommand specifically, not any positional.
_WRAPPERS_REQUIRING_RUN: frozenset[str] = frozenset({"poetry", "pipenv"})
# R8-1-PROCSUB / R8-2-SUBST: process substitution `>(cmd)`/`<(cmd)` and command substitution
# `$(cmd)`/`` `cmd` `` are SYNTAX FORMS that introduce inner execution sites the shlex-tokenized
# first-command walk doesn't see. Pre-scan the raw segment for these and ask whether an inner
# command (or, for command-substitution, ANY bare token inside) is an interpreter. The bare-token
# fallback for `$(...)` is the trade for catching `$(echo bash)` (echo isn't the interpreter, but
# its OUTPUT is the literal `bash` that the outer pipe then executes — there is no way to know
# what echo returns without evaluating it, so we conservatively flag any cmd-sub whose body
# contains an interpreter token); the FP cost (e.g. `$(grep python)` flags) is small because
# command substitution containing an interpreter NAME is unusual in CI workflows.
_PROCSUB_RE = re.compile(r"[<>]\(([^()]*)\)")
_CMDSUB_PAREN_RE = re.compile(r"\$\(([^()]*)\)")
_CMDSUB_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _basename_if_absolute(token: str) -> str:
    """Strip a path prefix only when the path is ABSOLUTE.

    R5-1-FN: `/usr/bin/bash` is a real interpreter reference, basenamed to `bash`. A RELATIVE
    path like `./tools/bash` or `foo/bar/bash` names a local executable that is NOT the system
    interpreter, so it stays literal and won't match the interpreter set.
    """
    return token.rsplit("/", 1)[-1] if token.startswith("/") else token


def _token_is_interpreter(token: str) -> bool:
    # The lookup is case-insensitive so `R`/`Rscript`/`OSAScript` resolve correctly across
    # platform-typical name capitalizations.
    name = _basename_if_absolute(token).lower()
    return name in _INTERPRETERS or bool(_PYTHON_INTERP_RE.match(name))


def _token_is_wrapper(token: str) -> bool:
    return _basename_if_absolute(token).lower() in _FETCH_WRAPPERS_SET


def _first_executed_command(tokens: list[str]) -> str | None:
    """After stripping inline VAR=val + wrappers + their flags, return the first command token.

    Factored out of `_fetch_pipe_violation` so the same logic can be reused for process-substitution
    bodies (R8-1-PROCSUB). Returns None if the token list is empty after stripping.
    """
    tokens = list(tokens)
    while tokens:
        head = tokens[0]
        if _INLINE_ASSIGN_RE.match(head):
            tokens.pop(0)
            continue
        if not _token_is_wrapper(head):
            return head
        wrapper = _basename_if_absolute(tokens.pop(0)).lower()
        # R8-3-WRAPPERS: wrappers like `sg <group> cmd`, `flock <path> cmd`, `chroot <path> cmd`,
        # `timeout <duration> cmd` reserve a bare positional for a non-command operand (group
        # name / lock path / chroot path / duration); that slot is NEVER the command. Consume it
        # unconditionally (only guarding against `-flag`, which the flag loop below handles).
        # Without the unconditional consume, `chroot /r ls` mistakes `/r` for the R interpreter
        # via basename normalization, and `sg root bash` never reaches `bash` as the command.
        if wrapper in _WRAPPERS_WITH_POSITIONAL_ARG and tokens and not tokens[0].startswith("-"):
            tokens.pop(0)
        # R8-10: `poetry run X` / `pipenv run X` only execute X when gated by the literal
        # `run` subcommand. Other subcommands (`poetry add`, `pipenv install`, …) don't execute
        # what follows, so consuming any positional would cause `poetry add bash` to falsely flag.
        if wrapper in _WRAPPERS_REQUIRING_RUN and tokens and tokens[0] == "run":
            tokens.pop(0)
        while tokens and tokens[0].startswith("-"):
            tokens.pop(0)
            if (
                tokens
                and not tokens[0].startswith("-")
                and not _token_is_wrapper(tokens[0])
                and not _token_is_interpreter(tokens[0])
                and not _INLINE_ASSIGN_RE.match(tokens[0])
            ):
                tokens.pop(0)
    return None


def _tokenize_segment(segment: str) -> list[str]:
    """shlex-tokenize a pipe segment; on parse error, fall back to whitespace split but STRIP
    leading/trailing quote characters per token (R8-4-UNCLOSED-QUOTE — without the strip, an
    unclosed quote would leave the literal `"` attached to the interpreter name and evade)."""
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return [tok.strip("\"'") for tok in segment.split()]


def _balanced_paren_bodies(segment: str, opener: str) -> list[str]:
    """Return the inner-body strings of every top-level balanced `<opener>(…)` in ``segment``.

    Used by `_inner_execution_is_interpreter` to extract process/command substitution bodies that
    may contain NESTED parens (e.g. `tee >(sh -c "$(cat)")`). A plain `[^()]*` regex can't span
    nested parens — using a stack-based scan handles arbitrary depth correctly. The opener is
    the literal character/sequence immediately before `(`: `>` or `<` for process substitution,
    `$` for command substitution. Returns empty list if no balanced pair is found.
    """
    bodies: list[str] = []
    i = 0
    op_len = len(opener)
    while i < len(segment) - op_len:
        if segment[i : i + op_len] == opener and segment[i + op_len : i + op_len + 1] == "(":
            depth = 1
            start = i + op_len + 1
            j = start
            while j < len(segment) and depth > 0:
                if segment[j] == "(":
                    depth += 1
                elif segment[j] == ")":
                    depth -= 1
                    if depth == 0:
                        bodies.append(segment[start:j])
                        i = j + 1
                        break
                j += 1
            else:
                # unclosed paren — give up on this scan
                break
            continue
        i += 1
    return bodies


def _inner_execution_is_interpreter(segment: str) -> bool:
    """R8-1-PROCSUB / R8-2-SUBST: does the segment contain a process-substitution OR command-
    substitution whose inner execution is an interpreter? The pipe semantics of `tee >(bash)` and
    `$(echo bash)` route the fetched stream into bash regardless of what the outer "first command"
    is. We pre-scan the raw segment for these syntax forms BEFORE the shlex tokenizer sees them
    (shlex emits each as a single opaque token, so the outer walk misses them by design).

    For process substitution (`>(cmd)`/`<(cmd)`): the inner's first command is the executor.
    For command substitution (`$(cmd)`/`` `cmd` ``): the substitution's output BECOMES the next
    command, so we conservatively flag if ANY token inside is an interpreter (catches the
    `$(echo bash)` form where the output literal IS the interpreter name). FP risk is small —
    a workflow `run:` body containing `$(grep python …)` is unusual.

    A balanced-paren scan (`_balanced_paren_bodies`) handles arbitrary nesting like
    `tee >(sh -c "$(cat)")` — a plain `[^()]*` regex couldn't span the nested `$(cat)`.
    """
    for inner in _balanced_paren_bodies(segment, ">") + _balanced_paren_bodies(segment, "<"):
        inner_cmd = _first_executed_command(_tokenize_segment(inner))
        if inner_cmd is not None and _token_is_interpreter(inner_cmd):
            return True
    for inner in _balanced_paren_bodies(segment, "$"):
        for tok in _tokenize_segment(inner):
            if _token_is_interpreter(tok):
                return True
    for match in _CMDSUB_BACKTICK_RE.finditer(segment):
        for tok in _tokenize_segment(match.group(1)):
            if _token_is_interpreter(tok):
                return True
    return False


def _fetch_pipe_violation(line: str) -> str | None:
    """If ``line`` is `curl|wget … | <interpreter>`, return the offending pipeline; else None.

    Walks pipe segments left-to-right after a `curl`/`wget` is found. For each segment, three
    checks IN ORDER:

      1. **Inner execution** (R8-1-PROCSUB / R8-2-SUBST). Pre-scan the raw segment for process
         substitution `>(cmd)`/`<(cmd)` or command substitution `$(cmd)`/`` `cmd` `` whose inner
         is an interpreter. These syntax forms shlex sees as opaque tokens but the shell DOES
         execute them — so the outer first-command walk would miss `curl … | tee >(bash)` and
         `curl … | $(echo bash)`. Pre-scanning before tokenization handles them.
      2. **Tokenized first command**. shlex-tokenize the segment; strip inline `VAR=val` env
         assignments and wrapper runs (each wrapper consumes its `-flag` options + optionally one
         non-dash value). The first surviving token, after `_first_executed_command`, is the
         executed command — flagged iff it matches the closed interpreter set.

    Wrappers come from a closed set (`_FETCH_WRAPPERS_SET`); interpreters from another closed set
    (`_INTERPRETERS` + `_PYTHON_INTERP_RE` for `python[N]`). Adding a new shell idiom is a list
    edit — NOT a regex restructure.
    """
    if not _FETCH_CMD_RE.search(line):
        return None
    parts = line.split("|")
    if len(parts) < 2:
        return None
    for segment in parts[1:]:
        # 1. Inner execution via proc-sub / cmd-sub (pre-tokenization scan).
        if _inner_execution_is_interpreter(segment):
            return line.strip()
        # 2. Tokenized first-command check.
        tokens = _tokenize_segment(segment)
        first = _first_executed_command(tokens)
        if first is not None and _token_is_interpreter(first):
            return line.strip()
    return None


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
    """Return shell-invoked tools/images not pinned by digest/checksum/version (§11.3)."""
    # R3-1-DOCKERX: a full-comment line (shell `#` comment, or a YAML comment) is documentation, not
    # an invocation — a prose mention of "docker run …" / "curl … | bash" must not be flagged. Drop
    # such lines before scanning. (An inline trailing comment on a REAL command is left intact, so a
    # genuine `docker run img:tag  # note` is still caught.)
    # R8-5-CONT: fold shell line continuations BEFORE the per-line scan so the canonical
    # multi-line install pattern `curl -fsSL https://example.com/install \⏎  | bash` is treated as
    # one logical line. Without this, the detector iterates `text.splitlines()` and never sees a
    # `|` on the curl line. (`re.MULTILINE` not needed: `\n` is matched literally; the leading
    # whitespace of the next line is the operator-formatted indent.)
    text = re.sub(r"\\\n[ \t]*", " ", text)
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    violations: list[str] = []
    for match in _DOCKER_RUN_RE.finditer(text):
        image = _docker_run_image(match.group("rest"))
        if image is not None and not _DIGEST_RE.search(image):
            violations.append(f"docker image not digest-pinned: {image}")
    # Fetch-and-execute detection is line-oriented: a pipeline lives on a single line, and the
    # shlex tokenizer needs to see it whole (intermediate `|` are the pipe segments we walk).
    for line in text.splitlines():
        pipeline = _fetch_pipe_violation(line)
        if pipeline is not None:
            violations.append(f"fetch-and-execute without checksum: {pipeline}")
    for match in _PIP_INSTALL_RE.finditer(text):
        for pkg in _unpinned_pip_packages(match.group("rest")):
            violations.append(f"pip-installed tool not pinned to an exact version: {pkg}")
    return violations


# docker run/pull flags that consume a SEPARATE following token as their value (review #D): the
# token right after one of these is the flag's argument, NOT the image — e.g. in
# `docker run -e FOO=bar alpine:3.19`, `FOO=bar` must be skipped so `alpine:3.19` is evaluated.
# A `--flag=value` form carries its own value and needs no skip.
_DOCKER_VALUE_FLAGS = frozenset(
    {
        "-e",
        "--env",
        "-v",
        "--volume",
        "-p",
        "--publish",
        "-w",
        "--workdir",
        "--mount",
        "-l",
        "--label",
        "--name",
        "--network",
        "--net",
        "-u",
        "--user",
        "--entrypoint",
        "--add-host",
        "--device",
        "--tmpfs",
        "--cap-add",
        "--cap-drop",
        "--platform",
        "-h",
        "--hostname",
        "--env-file",
        "--restart",
        "--pull",
    }
)


def _docker_run_image(rest: str) -> str | None:
    """The image argument of a ``docker run``/``docker pull`` invocation.

    Skips both valueless option flags (``--rm``, ``-i``) and value-taking flags together with
    the separate token they consume (``-e VAR=x``, ``-v a:b``), so the first remaining bare
    token is the actual image — closing the token-shift false-negative (review #D).
    """
    tokens = rest.split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            # A bare value-taking flag consumes the next token; `--flag=value` carries its own.
            i += 2 if ("=" not in token and token in _DOCKER_VALUE_FLAGS) else 1
            continue
        return token
    return None


def action_pin_violations(root: Path) -> list[str]:
    """Scan workflows + scaffolded workflow bodies for unpinned third-party actions.

    Returns ``file: ref`` strings. Placeholders like ``@{{ aviato-ref }}`` in scaffold
    bodies are skipped (they pin the Library, resolved at scaffold time).
    """
    # GitHub Actions accepts BOTH .yml and .yaml, so an unpinned action in a `*.yaml`
    # workflow must not escape the pin check (matches validation._yaml_files, §11.3).
    root = Path(root)
    workflow_dir = root / ".github" / "workflows"
    scaffold_dir = root / "aviato" / "library" / "scaffold" / "files"
    targets = sorted(p for ext in ("*.yml", "*.yaml") for p in workflow_dir.glob(ext))
    targets += sorted(p for ext in ("wf-*.yml", "wf-*.yaml") for p in scaffold_dir.glob(ext))
    violations: list[str] = []
    for path in targets:
        # R5-4-LINT: `lint-actions <consumer>` points this at an operator-supplied tree, so a
        # workflow with invalid UTF-8 (or a binary file named *.yml) must NOT leak a raw
        # UnicodeDecodeError past main()'s net. errors="replace" is safe — the scan is a
        # regex/substring pass, so replacement chars never create or mask a real match. Mirrors
        # diagnosis._has_drift_automation, which reads the same workflow dir the same way.
        text = path.read_text(encoding="utf-8", errors="replace")
        for ref in unpinned_third_party_uses(text):
            if "{{" in ref:  # scaffold placeholder, not a real mutable tag
                continue
            violations.append(f"{path.name}: {ref}")
        # The in-CI lint definition itself embeds the docker/fetch DETECTOR patterns (as grep
        # arguments + comments), which this text scan cannot distinguish from real invocations.
        # Its actual tool invocations (hadolint's @sha256:-pinned image, actionlint's
        # download-to-file-then-checksum) are pinned and reviewed, so skip the tool-invocation
        # text scan for it (the `uses:` digest check above still applies). § _LINT_DEFINITION_FILE.
        if path.name == _LINT_DEFINITION_FILE:
            continue
        for tool in unpinned_tool_invocations(text):
            violations.append(f"{path.name}: {tool}")
    # R4-4/R4-5: a seeded requirements file is installed by CI (`pip install -r requirements*.txt`);
    # its tool pins must be exact, but a floor inside it is invisible to the `pip install` token scan
    # above (the `-r <path>` is skipped). Scan the seed bodies directly. R2-2-PIPR: glob ALL seeded
    # `requirements*.txt.txt` bodies (not just the dev one) so any future seeded requirements file is
    # covered. (Scope note: a workflow's `-r <file>` pointing at a NON-seeded, consumer-authored file
    # is out of scope here — `aviato validate` runs in the Library checkout, where the only
    # requirements files are these seeds; a consumer's own requirements policy is theirs to own.)
    for req in sorted(scaffold_dir.glob("requirements*.txt.txt")):
        for pkg in unpinned_requirements_lines(req.read_text(encoding="utf-8", errors="replace")):
            violations.append(f"{req.name}: requirement not pinned to an exact version: {pkg}")
    return violations


# The workflow that DEFINES the in-CI pin gate — it necessarily embeds the docker/fetch detector
# patterns, so it is exempt from the tool-invocation TEXT scan (but not the uses: digest check).
_LINT_DEFINITION_FILE = "reusable-common-lint.yml"
