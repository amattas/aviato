# CLI reference

Every Aviato subcommand, grouped by lifecycle stage. Section (§) references point
at the requirements index (`docs/requirements/README.md`). Run
`aviato <command> --help` for the full flag surface of any command.

Aviato keeps no persistent inventory: commands target a local root, one explicit
local checkout, or one `OWNER/REPO`. Privileged changes are always
operator-initiated and, where they touch settings, gated (§5.7/§5.8).

## Adoption

**`aviato onboard PATH|OWNER/REPO --profile P --pin X.Y.Z`** — plan or adopt a
repository (§5.2). Plans by default; `--write` applies the plan locally,
`--open-pr` adopts a remote repository via a reviewable scaffold PR. `--docs`
composes the opt-in docs deploy (§13.3); repeat `--var KEY=VALUE` for non-secret
profile variables; `--allow-dirty` acknowledges a non-clean worktree. The pin
must resolve to a published tag/branch; re-onboarding preserves the existing pin.

```bash
aviato onboard . --profile python-library --pin 1.2.3 --docs --write
```

**`aviato provision OWNER/REPO --profile P --pin X.Y.Z`** — create, stage-protect,
and scaffold a brand-new repository (§5.2/§2.11). Private by default; add
`--public` to create a public repository.

```bash
aviato provision amattas/example --profile node-service --pin 1.2.3
```

**`aviato apply-rulesets OWNER/REPO`** — dry-run (default) or `--apply` the GitHub
rulesets (§5.6). With `--declaration` it resolves checks and approvals through the
consumer's declared overrides — the payload that settings-drift remediation
recommends. Without a declaration it dry-runs a base profile only.

```bash
aviato apply-rulesets OWNER/REPO --apply --declaration /path/.github/aviato.yml
```

**`aviato complete-protection /path/to/consumer`** — idempotently (re-)apply full
branch protection; the §5.2 recovery path.

## Ongoing operations

**`aviato doctor /path/to/consumer`** — classify managed artifacts and probe their
health (§5.4), including the consumer's [aviato-bot](https://github.com/amattas/aviato-bot)
drift coverage. Set `AVIATO_BOT_URL` and `AVIATO_BOT_STATUS_TOKEN` to enable the
probe; without them the `bot status:` line reads `unconfigured`. `doctor` exits
non-zero only when a configured probe reports a repo the bot does not cover or the
probe errors.

**`aviato sync /path/to/consumer`** — materialize managed artifacts, including the
caller workflows (§5.3/§15). `--rebaseline-seeds` accepts current seed-once
contents as the new baseline; `--override-version-pin` is the recovery switch for
a recorded-pin mismatch.

Scheduled file/settings drift reporting is no longer a CLI command. Drift
detection (§5.5/§5.6) is owned by the [aviato-bot](https://github.com/amattas/aviato-bot)
service — settings-event webhooks plus a weekly fleet sweep — which opens
file-drift proposals and files settings-drift tracking issues. `doctor`/`scan`
surface that coverage (see below); the operator applies drift through the gated
`reconcile` command.

**`aviato reconcile /path/to/consumer ISSUE --confirm DIFF_ID`** — operator-gated,
diff-bound settings apply (§5.7). Fail-closed: the consent label must be present
and the `DIFF_ID` must still match the live diff.

**`aviato scan /path/a /path/b`** — read-only fleet diagnosis (§5.11); `--fix`
opens managed-file proposals and `--audit` surfaces open settings-drift tracking
issues (§5.5). Each row includes a `bot=` drift-coverage column
(`unconfigured`/`covered`/`uncovered`/`error`/`not-probed`) from the aviato-bot
probe; set `AVIATO_BOT_URL` and `AVIATO_BOT_STATUS_TOKEN` to enable it.

**`aviato repin /path/to/consumer X.Y.Z`** — move the Library version pin (§5.12);
`--write` applies locally, `--open-pr` opens a reviewable re-pin proposal.

**`aviato offboard /path/to/consumer`** — remove a repository from Aviato
management (§5.13). `--write` removes management state but preserves managed files
unless `--delete-files` is also given; `--open-pr` opens a reviewable removal
proposal.

```bash
aviato scan /path/a /path/b --fix --audit
```

## Release and versioning

**`aviato next-version --current X.Y.Z --commit "feat: x"`** — derive the next
SemVer from Conventional Commits (§5.9).

**`aviato bump-version X.Y.Z /path/to/consumer`** — write the version into the
version-source locations (§3.3).

**`aviato is-highest 1.2.3 1.0.0 1.2.3`** — exit 0 iff the first argument is the
highest release among the rest; the §8.14 monotonic-alias gate.

**`aviato render-rulesets`** — print the rendered ruleset JSON.

## Library-only

**`aviato validate`** — validate the policy infrastructure, agnosticism, digest
pins, template parity, and inline monotonic-alias parity. Runs from a **source
checkout only**, not a pip-installed package.

**`aviato lint-actions [PATH]`** — the §11.3 supply-chain gate: zizmor over
`uses:`/image pinning plus a fail-closed `curl|bash` check and non-exact pip pin
detection.

```bash
aviato validate
```

The legacy `scripts/audit-repos.sh` and `scripts/apply-rulesets.sh` wrappers exec
the CLI and still work.
