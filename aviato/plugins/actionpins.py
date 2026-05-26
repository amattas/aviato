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
_USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)
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


# §11.3 covers shell-fetched tools/images too, not just `uses:` refs. Two well-defined
# anti-patterns are detected: a `docker run`/`docker pull` image without an `@sha256:` digest, and
# a remote artifact fetched and piped straight into a shell/extractor (no checksum gate).
# CX#7: match BOTH run and pull so `aviato validate` agrees with the in-CI reusable-common-lint
# gate (which already scans `docker (run|pull)`) — an unpinned `docker pull alpine:3.19` is just as
# much a mutable-image supply-chain risk as `docker run`.
_DOCKER_RUN_RE = re.compile(r"\bdocker\s+(?:run|pull)\b(?P<rest>[^\n]*)")
_FETCH_PIPE_RE = re.compile(r"\b(?:curl|wget)\b[^\n|]*\|[^\n]*\b(?:sh|bash|tar)\b")

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
    """
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
    violations: list[str] = []
    for match in _DOCKER_RUN_RE.finditer(text):
        image = _docker_run_image(match.group("rest"))
        if image is not None and "@sha256:" not in image:
            violations.append(f"docker image not digest-pinned: {image}")
    for match in _FETCH_PIPE_RE.finditer(text):
        violations.append(f"fetch-and-execute without checksum: {match.group(0).strip()}")
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
        text = path.read_text(encoding="utf-8")
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
    # R4-4/R4-5: the seeded dev-requirements file is installed by the container-service CI
    # (`pip install -r requirements-dev.txt`); its tool pins must be exact, but a floor inside it
    # is invisible to the `pip install` token scan above (the `-r <path>` is skipped). Scan the
    # seed body directly. Materialized seed bodies carry a `.txt.txt` suffix in the scaffold dir.
    for req in sorted(scaffold_dir.glob("requirements-dev.txt.txt")):
        for pkg in unpinned_requirements_lines(req.read_text(encoding="utf-8")):
            violations.append(f"{req.name}: requirement not pinned to an exact version: {pkg}")
    return violations


# The workflow that DEFINES the in-CI pin gate — it necessarily embeds the docker/fetch detector
# patterns, so it is exempt from the tool-invocation TEXT scan (but not the uses: digest check).
_LINT_DEFINITION_FILE = "reusable-common-lint.yml"
