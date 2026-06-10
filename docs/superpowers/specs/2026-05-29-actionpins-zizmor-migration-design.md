# Design — Replace the flapping supply-chain detector with zizmor + a fail-closed fetch check

**Date:** 2026-05-29
**Status:** implemented (shipped 2026-05/06; retained as the design record)
**Author:** review cycle 9 follow-up (Opus + Codex)

## 1. Problem

`aviato/plugins/actionpins.py` (601 lines) plus its in-CI twin in
`.github/workflows/reusable-common-lint.yml` (the `interps='…'` grep, the docker-token extractor)
implement §11.3 supply-chain enforcement three ways:

1. unpinned third-party `uses:` actions (must be 40-hex SHA),
2. un-digest-pinned container images,
3. `curl … | bash` fetch-and-execute without a checksum,

plus a pip exact-version check. Job (3) requires statically deciding whether arbitrary shell
executes fetched bytes — **undecidable** — so it has been rewritten in **8 commits** (+366/−14 in the
latest alone) and *still* fails: cycle-9 review found it misses the most common real idioms
(`bash -c "$(curl …)"`, `bash <(curl …)`, dynamic `$B`, YAML-folded `run:`), while raising
false-positives (`curl | awk`, quoted docs). The Python detector and the in-CI grep also disagree on
5 of 6 axes (R9-5), and the parity test checks only 1. This is the codebase's one true flap.

The non-detector jobs (1, 2, pip) are tractable and have mature, maintained tooling
([zizmor](https://docs.zizmor.sh/), Trail-of-Bits-maintained, validated against 41k workflows).

## 2. Goals / non-goals

**Goals**
- Delete the hand-rolled `uses:`/docker/fetch machinery and the in-CI grep mirror (~1,000 lines incl. tests).
- One implementation of every check, run identically by consumer CI and `aviato validate` — no second
  implementation to drift against (closes R9-5 by construction).
- Replace the undecidable fetch-execute detector with a **fail-closed** rule (closes R9-1…R9-4 as
  *flagged*; R9-6…R9-8 handled by an explicit allowlist).
- Record the fail-closed decision durably in the docs so future review cycles do not re-introduce
  interpreter enumeration (anti-flap).

**Non-goals**
- Re-deriving zizmor's broader audits (template-injection, excessive-permissions, etc.). We adopt
  `unpinned-uses` + `unpinned-images`; other audits are a future opt-in, out of scope here.
- Changing the §11.3 *policy* (first-party + Library self-ref may be ref-pinned; everything else SHA;
  images digest-pinned; pip exact-version). Only the *mechanism* changes.

## 3. Design

### 3.1 Single entry point: `aviato lint-actions [PATH]`
`aviato lint-actions` becomes the sole implementation, invoked by both consumer CI and
`aviato validate`. It runs, in order, and aggregates violations:

1. **zizmor** (`unpinned-uses` + `unpinned-images`) on `PATH/.github/workflows/`.
2. **fail-closed fetch-execute** check (§3.4) on the same workflow bodies.
3. **pip exact-version** check (kept as-is) on workflow bodies + seeded `requirements*.txt.txt`.
4. **placeholder-aware `uses:` SHA check** (§3.3) on scaffold bodies only (zizmor can't parse them).

The **in-CI grep mirror is removed** from `reusable-common-lint.yml`.

### 3.2 zizmor for `uses:` + images (a pinned dependency of `aviato`)
- `zizmor` is declared as an **exact-version dependency** of `aviato` (e.g. `zizmor==<X.Y.Z>` in
  `pyproject.toml`), so `pip install aviato==<ver>` brings the pinned zizmor. This satisfies §11.3's
  own "tools are version-pinned" rule for zizmor itself.
- A **bundled `zizmor.yml`** ships inside the package under `aviato/library/` (alongside `policy.yml`
  — single source of truth, ships in the wheel). `aviato lint-actions` invokes
  `zizmor --config <bundled zizmor.yml> --format json <target>` and maps findings into its violation
  list. Consumers get the Library's policy without authoring their own config.
- Policy block (verified expressible; most-specific match wins):
  ```yaml
  rules:
    unpinned-uses:
      config:
        policies:
          actions/*: ref-pin
          github/*: ref-pin
          amattas/aviato/*: ref-pin   # the one sanctioned mutable Library self-ref (§6.1/§11.3)
          "*": hash-pin
  ```
  `ref-pin` = symbolic-or-SHA allowed; `hash-pin` = SHA required.
- Exit/parse: zizmor returns non-zero on findings; `aviato lint-actions` parses `--format json`,
  surfaces each as a `file: finding` line, and exits non-zero if any check (zizmor or Python) found
  a violation.

### 3.3 Scaffold-body handling
`aviato/library/scaffold/files/wf-*.yml` are *templates* containing `{{ aviato-ref }}` placeholders;
zizmor cannot parse them as live workflows. They keep a **tiny placeholder-aware `uses:` SHA check**
in Python (the existing `_USES_RE` + skip-`{{`-refs logic, ≈10 lines). These bodies are
maintainer-authored and the only mutable ref they carry is the templated Library ref. This is the
**only** `uses:`-checking Python that survives; it does not flap.

### 3.4 Fail-closed fetch-execute check (replaces ~380 lines with ~30)
Operate on **logical lines** (fold YAML `>`/`|` block scalars and `\`-newline continuations first,
so `curl …|⏎bash` and folded blocks are one line — closes R9-2).

A logical line is a **violation** iff:
- it contains `curl` or `wget`, **and**
- it contains a pipe into a command (`| <cmd>`) **or** a substitution that can execute
  (`<(…)`, `>(…)`, `$(…)`, `` `…` ``),
- **and it does NOT positively prove safety**, where "safe" means *either*:
  - a checksum/verification token is present on the line — `sha256sum`, `shasum`, `cosign verify`,
    `gpg --verify`; **or**
  - the fetched output flows only into an **allowlisted non-executing sink**: `jq`, `grep`, `tee`
    to a file, or a `>`/`>>` redirect to a file (no interpreter).

No interpreter enumeration, no wrapper list, no proc-sub depth scanner. The default for anything not
provably safe is **reject** (fail-closed). Consequences on the cycle-9 corpus:
- `curl … | bash`, `bash -c "$(curl …)"`, `bash <(curl …)`, `B=bash; curl … | $B`, folded `run:` →
  **flagged** (R9-1…R9-4 closed).
- `curl … | jq .`, `curl … | grep x`, `printf '… | bash'` (no real curl pipe), `curl -o f &&
  sha256sum -c && bash f` → **pass** (R9-6…R9-8 / legitimate verified installs).

This is consistent with the codebase's existing fail-closed posture (§2.7 "fail closed on an
ambiguous read", §5.14 "absence/unreadable reads as broken, not clean"); the current fetch detector
is the lone fail-*open* outlier.

### 3.5 pip exact-version check — kept
`_unpinned_pip_packages` / `unpinned_requirements_lines` are tractable and never flapped; they remain
unchanged, called from `aviato lint-actions`.

### 3.6 Consumer CI (`reusable-common-lint.yml`)
Replace the two grep steps ("Third-party action digest pin", "Container image + fetched-binary pin")
with a single step:
- `pip install` aviato **from the reusable-workflow's own ref** —
  `pip install "aviato @ git+https://github.com/amattas/aviato@${GITHUB_ACTION_REF}"` — which works
  for both a tag and a SHA pin and guarantees the installed code matches the pinned workflow (no
  version-skew). This brings the pinned zizmor transitively. (If/when aviato is published to PyPI, an
  exact `aviato==<ver>` matching the ref is an equivalent alternative.)
- run `aviato lint-actions .`.

This is consistent with the job already `pip install`ing yamllint and downloading actionlint by
checksum. The `_LINT_DEFINITION_FILE` text-scan exemption is **removed** (the file no longer embeds
detector patterns; its only tool invocations are the exact-pinned `pip install` + zizmor).

### 3.7 `aviato validate`
`_check_action_pins` calls `aviato lint-actions` internals on the Library's own workflows + scaffold
bodies. The monotonic-alias/template-parity checks are unchanged. The grep↔Python parity check is
deleted (no grep mirror).

## 4. What gets deleted
`_fetch_pipe_violation`, `_first_executed_command`, `_tokenize_segment`, `_balanced_paren_bodies`,
`_inner_execution_is_interpreter`, `_INTERPRETERS`, `_PYTHON_INTERP_RE`, `_FETCH_WRAPPERS_SET`,
`_WRAPPERS_WITH_POSITIONAL_ARG`, `_WRAPPERS_REQUIRING_RUN`, `_PROCSUB_RE`/`_CMDSUB_*`,
`_docker_run_image`, `_DOCKER_VALUE_FLAGS`, `_DOCKER_RUN_RE`; the two grep steps in
`reusable-common-lint.yml`; and their tests (`test_cilint_interps_mirror_actionpins`, the
fetch-pipe TP/FP corpus, the docker-token-extractor tests). ≈1,000 lines.

## 5. Docs updated (anti-flap — explicit requirement)
- **REQUIREMENTS.md §11.3** — fetch-execute detection is **fail-closed by policy**: it does NOT
  enumerate interpreters; any unverified fetch-pipe is rejected. `uses:`/image pinning is delegated
  to zizmor.
- **CLAUDE.md** — rewrite the actionpins section: grep mirror gone; uses/images via bundled-config
  zizmor; curl via the fail-closed Python rule; record the decision + rationale.
- **ARCHITECTURE.md** — zizmor named as the action/image-pinning engine (a pinned dependency); note
  the bundled `zizmor.yml` as policy data.
- **Inline docstring** on the fail-closed function — "DO NOT convert this back to interpreter
  enumeration: that fails open and flapped for 8 cycles (see cycle-9 findings R9-1…R9-5). This is
  intentionally fail-closed — unknown downstream ⇒ reject."

## 6. Testing
- New fail-closed tests: every cycle-9 bypass (R9-1…R9-4) **flags**; allowlist/verified cases
  (R9-6…R9-8, checksum'd installs) **pass**; YAML-folded + continuation forms **flag**.
- zizmor integration: a fixture workflow with an unpinned `uses:` flags; an `actions/*` ref-pin
  passes; the `amattas/aviato/*` self-ref passes; a non-first-party tag fails. (Run against the
  bundled config.)
- Assert `zizmor` is pinned to an exact version in `pyproject.toml`.
- Delete obsolete tests (§4). Full `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh` green.

## 7. Supply-chain of the new tool
- `zizmor` pinned exact in `aviato` deps; bumped by Dependabot like other tool pins.
- Consumer CI installs a pinned `aviato` (by ref or exact version); no floating installs.

## 8. Risks & mitigations
- **Heavier consumer lint job** (`pip install aviato` + zizmor). Accepted: the job already installs
  pip tools; the coupling was explicitly chosen for single-implementation parity.
- **zizmor output/exit contract changes across versions.** Mitigated by the exact-version pin +
  `--format json` parsing + an integration test that fails if the contract drifts.
- **Fail-closed false-positives** in real consumer workflows. Accepted by design (visible, fixable);
  the allowlist covers the common data-sink cases. A pre-merge scan of current Library workflows
  confirms zero false-positives there before rollout.

## 9. Acceptance criteria
1. `reusable-common-lint.yml` contains no `interps=`/docker-token grep; one `aviato lint-actions` step.
2. `actionpins.py` contains no interpreter/wrapper/proc-sub/docker-token code; only the pip check, the
   scaffold-body `uses:` check, and the fail-closed fetch check + a thin zizmor wrapper.
3. `aviato validate` and consumer CI run the identical code path.
4. zizmor pinned; bundled `zizmor.yml` carries the policy.
5. Docs (REQUIREMENTS §11.3, CLAUDE.md, ARCHITECTURE.md, inline docstring) record the fail-closed
   decision.
6. `AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh` green; new tests cover R9-1…R9-8.
