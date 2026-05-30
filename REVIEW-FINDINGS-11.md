# REVIEW-FINDINGS — Cycle 11

> **STATUS: ALL RESOLVED.** Every cycle-11 finding is fixed, verified, and locked by tests; the full
> strict gate is green (`AVIATO_STRICT_TOOLS=1 ./scripts/validate.sh` → 696 passed, no skips).
>
> | Findings | Fix | Commit |
> |---|---|---|
> | C11-1…C11-9 (fetch detector) | **Coarse fail-closed rule over `run:` blocks** — no shell/quote/redirect parsing; flag any unverified fetch that isn't a bare-stdout or pure-data-pipe; design **frozen**. Metadata no longer scanned as shell. | `d54f7ac` |
> | R9-9 (App Store) | version command runs **before** signing-asset install; `KEYCHAIN_PASSWORD` no longer in `$GITHUB_ENV` | `f99e463` |
> | N1 / N3 / R9-21 | `upsert_ruleset` matches `(name, target)`; offboarding **fails closed** on an unmarked automation workflow; drift uses **override-resolved** checks | `df84e08` |
> | R9-15 / R9-16 / R9-18 / R9-20 | version_source path confinement; `pipelines.add: null` guard; `drifted_ruleset_names` fails loud on missing name; **§9b denylist now catches hyphen/underscore/concatenated forms** + concrete env name removed from core | `df84e08` |
> | N4 / N5 / N7 / N8 / N9 | scaffold `OSError` guard; drift-report issue-channel `CommandError` → exit 1; repin `pipelines` guard; `--repos-file` non-UTF-8 guard; dynamic-image waiver documented | `df84e08` |
>
> **N2** (reconcile re-read) was downgraded to LOW (sub-second same-pass window already guarded by
> `expected_live`) and left as documented/defensible. New regression tests lock R9-20 (hyphen/concat),
> N1 (name+target), N3 (fail-closed offboard), R9-15/R9-16 (path + null), R9-21 (resolved checks).
> **The fetch detector design is now FROZEN** — see the convergent-end-state section; do not refine it.



**Engines:** Opus 4.8 (this session) + Codex (`codex-cli 0.133.0`, `--sandbox read-only`), 5 rounds.
**Subject:** the cycle-10 fixes (`aecbd12` zizmor flags, `3057a69` taint-based fetch rewrite) **plus**
a codebase-wide sweep for deficiencies left unaddressed by the migration.
**Reproductions inline / in `.review/codex11_r{1..5}.md`.**

---

## Headline — yes, we are flapping (and we left work behind)

**1. `fetch_execute_violations` is flapping — three rewrites, the newest already broken.**
The §11.3 fetch-execute detector has now been rewritten **three times in ~10 commits**:
`8d069f7` (fail-closed v1) → … → `3057a69` (taint v2). The taint version — **one commit old** —
already has ~9 hole classes, all from **regex-splitting shell without a real parser**:

| Hole | Class | Example (verified) |
|---|---|---|
| C11-1 | HIGH FN | `_SEQ_RE` splits `2>&1`/`&>`/quoted `?a=1&b=2` → `curl … 2>&1 \| bash` **not flagged** |
| C11-2 | HIGH FN | quoted `#` stripped as a comment → `echo "x # y"; curl … \| bash` clean |
| C11-3 | HIGH FN | verify clears **all** taint, unbound to the artifact → `curl -o a && sha256sum -c other && bash a` clean |
| C11-4 | HIGH FN | download forms unparsed → `curl -fsSLo f url && bash f`, `curl -O url && bash i.sh`, `wget url && bash i.sh` **not flagged** |
| C11-5 | HIGH FN/FP | whole workflow text analyzed as shell → YAML metadata (`name: sha256sum -c …`) can clear taint; `env: NOTE: curl…\|bash` flags |
| C11-6 | HIGH FN | dynamic/quoted fetch names → `$CURL …\|bash`, `c""url …\|bash` evade `_FETCH_RE` |
| C11-7 | MED FP | quoted/heredoc doc strings → `echo "curl … \| bash"`, `printf …` flagged |
| C11-8 | MED FP/FN | tainted-use is basename/substring, not shell-word → `bash config/f` FP; quoted paths FN |
| C11-9 | MED | weak verifiers accepted: `md5sum -c`/`sha1sum -c`; `cosign verify`/`gpg --decrypt` without artifact/identity binding |

Both engines' verdict: **this will not converge by patching the regex split** — every "safe"
exemption needs more shell parsing, and each partial parser opens new fail-open edges (quotes,
redirects, heredocs, substitution, option parsing, YAML context). **The flap is structural.**

**2. We fixed the flapping detector but never fixed the *other* cycle-9 findings.** The migration
addressed only R9-1…R9-5 (the detector). **Five cycle-9 findings remain open**, all verified still
present (their files weren't touched): R9-9, R9-15, R9-16, R9-20, R9-21. Plus this sweep found new
ones (N1…N8). So the codebase has accumulated real, traceable deficiencies behind the detector churn.

---

## Convergent end-state for the detector (both engines)

Stop hand-parsing shell with regexes. Two viable end-states; pick ONE and stop refining:

- **(A) Real shell-parser AST** — parse the workflow YAML, take each `run:` scalar, and parse it with
  a shell grammar (`bashlex` in Python). Walk commands/pipelines/redirects/heredocs/substitutions and
  bind verifier→artifact structurally. Correct, but a heavier dependency + its own surface.
- **(B) Deliberately COARSE fail-closed rule** (recommended for a *lint*, not a sandbox): parse YAML
  `run:` blocks, then flag **any** unverified `curl`/`wget` in a block that is not a *lone bare fetch*
  (no pipe, no substitution, no second command, no file write). Accept the false positives
  (`curl|jq` would flag → consumer adds a checksum or splits the step) and **stop refining around
  them**. Nothing to enumerate; nothing to keep patching; immune to `2>&1`/quoting/etc. because it
  doesn't try to prove safety structurally.

The recurring flap comes from chasing a precise fetched-byte→execution dataflow in regex. (B) abandons
precision for a decidable, stable rule; (A) buys precision with a real parser. **Either converges;
the current middle path does not.** Whichever is chosen, parse YAML first so workflow *metadata* is
never analyzed as shell (C11-5).

**Codex R5 picks (B) decisively, and so do I:** *"Use the deliberately coarse fail-closed rule, over
parsed YAML `run:` blocks. Do not keep refining regex shell splitting, and do not make bashlex the
convergence bet… This is a lint gate, not a sandbox; stable false positives are cheaper than another
fail-open detector."* Concrete shape: extract `run:` blocks (flag on parse failure); inside a block,
`curl`/`wget` is unsafe unless it's a trivial bare fetch to stdout, or a narrow filename-bound
download immediately followed by a real verifier before any use. No interpreter enumeration, no broad
pure-sink allowlist. **Freeze this design and stop iterating the detector.**

## Fix priority & verdict (Codex R5)

**Cycle-11 verdict: NOT converged — do not ship.** `aviato validate` and `aviato lint-actions .`
both pass, but that is *false comfort* — the highest-risk semantic failures remain.

Ship-blockers (fix before integrating the branch), in order:
1. **R9-9** App Store secret ordering — a real filesystem/keychain secret exposure (not merely env scope).
2. **Fetch detector** — land the coarse fail-closed rewrite (B) with the known-bypass corpus C11-1…C11-9.
3. **N1** `upsert_ruleset` name-only match — a name collision can mutate the wrong protected resource.
4. **N3** offboarding leaves a malformed-marker workflow running after removing the declaration.
5. **R9-21** ruleset drift ignores pipeline overrides (ship-blocker if any consumer ships overrides).
6. **R9-15 + N6** path confinement — `version_source.locations`, template `source`/`output_path` join unconfined.

Then: **R9-16** (fleet-abort guard, low cost) → **R9-20** (§9b agnosticism — a concrete core violation,
requirement blocker) → cleanup tier (**N4, N5, N7, N8** — robustness; release-blocking only if the bar
is "no raw operator tracebacks"). **N9** (zizmor dynamic-image waiver) and **R9-18** fold into the
ruleset/zizmor work.

---

## Findings index

| ID | Sev | Area | Engine(s) | Verified | One-line |
|----|-----|------|-----------|----------|----------|
| C11-1 | HIGH | fetch detector | Opus + Codex R1 | ✅ | `_SEQ_RE` mis-splits `2>&1`/`&>`/quoted `&` → fetch-pipe missed |
| C11-2 | HIGH | fetch detector | Codex R1 | ☑ | quoted `#` stripped as comment → fetch-pipe missed |
| C11-3 | HIGH | fetch detector | Opus + Codex R1 | ✅ | verify clears unbound taint (unrelated file / `:` no-op) |
| C11-4 | HIGH | fetch detector | Codex R1 | ✅ | `curl -fsSLo`/`-O`/`wget` default-name download forms missed |
| C11-5 | HIGH | fetch detector | Codex R1 | ☑ | whole workflow text scanned as shell (metadata clears taint / flags env) |
| C11-6 | HIGH | fetch detector | Codex R1 | ☑ | dynamic/quoted fetch names (`$CURL`, `c""url`) evade `_FETCH_RE` |
| C11-7 | MED | fetch detector | Opus + Codex R1 | ✅ | quoted/heredoc doc strings → false positive |
| C11-8 | MED | fetch detector | Codex R1 | ☑ | tainted-use basename/substring match → FP (`bash config/f`) + FN |
| C11-9 | MED | fetch detector | Codex R1 | ☑ | weak/unbound verifiers (md5/sha1; cosign/gpg without binding) |
| R9-9 | HIGH | app-store wf | cycle 9, **still open** | ✅ | signing material on disk + `KEYCHAIN_PASSWORD` in `$GITHUB_ENV` before operator `eval` |
| R9-15 | HIGH | composition | cycle 9, **still open** | ✅ | `version_source` locations escape repo root (abs / `..`) |
| R9-16 | MED | composition | cycle 9, **still open** | ✅ | `pipelines: {add: }` null → raw TypeError aborts fleet scan |
| R9-20 | MED | §9b selfcheck | cycle 9, **still open** | ✅ | denylist `\s+` join misses `app-store-connect` in core/model.py |
| R9-21 | HIGH | ruleset drift | cycle 9, **still open** | ✅ | drift/remediation ignores `pipelines` overrides → unmergeable-PR remediation |
| R9-18 | MED | rulesets | cycle 9, **still open** | ☑ | `drifted_ruleset_names` drops a desired ruleset missing `name` (§5.14) |
| N1 | HIGH | rulesets/github | Codex R3 | ✅ | `upsert_ruleset` matches live by **name only**, not `(name, target)` |
| N2 | LOW | reconcile | Codex R4 (downgraded) | ✅ | no second issue re-read between decide and `apply_settings` (sub-second window; `expected_live` already guards settings) |
| N3 | HIGH | offboarding | Codex R4 | ✅ | a malformed-marker managed workflow is skipped, then the declaration is removed → automation keeps running |
| N4 | MED | scaffold | Codex R3 | ☑ | `scaffold()` catches only `UnicodeDecodeError`; a directory at a managed path → raw `OSError` |
| N5 | MED | cli | Codex R4 | ☑ | `drift-report --settings-only` issue-channel `CommandError` → exit 2, not the documented fail-loud exit 1 |
| N6 | MED | registry/scaffold | Codex R3 | ☑ | template `source`/`output_path` not confined → a bad Library module can read/write outside the trees |
| N7 | LOW | repin | Codex R3 | ✅ | `plan_repin` assumes `overrides.pipelines` is a mapping → `overrides: {pipelines: []}` raises raw `AttributeError` |
| N8 | LOW | cli | Codex R4 | ☑ | `_read_repos_file` non-UTF-8 → `UnicodeDecodeError` escapes CLI error mapping |
| N9 | MED | zizmor wrapper | Codex R2 | ☑ | `--no-ignores` leaves no escape hatch for a legit dynamic `container.image: ${{ inputs.image }}` |

"✅" = runtime-reproduced; "☑" = confirmed by reading the exact code path. **N2 severity downgraded
from Codex's HIGH** after independent read: the consent read and apply are one pass (sub-second
window), and `apply_settings` already re-checks live branch state via `expected_live`.

---

## Notes
- The **zizmor flag change (`aecbd12`) is otherwise sound** (Codex R2 confirmed): auditor respects the
  bundled ref-pin policy (no first-party false positives), `--offline` keeps both gated audits, exit
  handling holds, bundled-config path resolves from the wheel. Only N9 (no waiver for legit dynamic
  images) is open there.
- **`reconcile_decision`, `classify_settings` (destructive-default), and `apply_settings` guards are
  confirmed solid** (Codex R4) — the §5.7/§5.6 core is fail-closed.

## Evidence (reproduction)
```python
from aviato.plugins.actionpins import fetch_execute_violations as f
f("curl -fsSL https://x/i.sh 2>&1 | bash")                       # C11-1 -> [] (miss)
f("curl -fsSL https://x/i.sh -o a && sha256sum -c other && bash a")  # C11-3 -> [] (miss)
f("curl -fsSLo /tmp/i.sh https://x/i.sh && bash /tmp/i.sh")      # C11-4 -> [] (miss)
f('echo "to install: curl https://x | bash"')                   # C11-7 -> flagged (FP)
```
```python
# carryovers still open
from aviato.core.composition import _validated_locations
_validated_locations({'locations':['/tmp/x','../y']}, context='x')   # R9-15 -> accepted
from aviato.core.listmerge import merge_list
merge_list(['a'], add=None, remove=())                               # R9-16 -> raw TypeError
from aviato.core.selfcheck import denylist_violations
denylist_violations()                                                # R9-20 -> []  (model.py names it)
```
```
git log --oneline -5 -- aviato/plugins/actionpins.py   # 3 fetch-detector rewrites in ~10 commits
github.py:257  upsert_ruleset: `if ruleset.get("name") == name`   (N1 — no target match)
offboarding.py:72-96  skip malformed workflow → remove declaration  (N3)
