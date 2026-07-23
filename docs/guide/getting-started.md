# Getting started

This guide walks an operator from a clean machine to a repository that Aviato
manages: install the CLI, satisfy the GitHub prerequisites, adopt or provision a
repository, and run the post-merge convergence sequence that a live adoption
requires. Aviato keeps no committed inventory of consumers — every command below
targets one explicit local checkout or `OWNER/REPO`, and every privileged change
is operator-initiated.

## Install

Install the published CLI from PyPI:

```bash
pip install aviato
```

Or install editable from a source checkout (this is also how you get the dev
tooling used by `aviato validate` and the local gate):

```bash
python3 -m pip install -e .[dev]
```

## Prerequisites

- **An authenticated `gh` CLI with admin on the target repositories.** Every
  GitHub interaction shells out to `gh api`; there is no token handling in
  Aviato itself. Rulesets, environments, and Pages configuration all require
  admin.
- **GitHub default-setup CodeQL must be disabled.** Aviato's security baseline
  owns CodeQL through the reusable security workflow, so GitHub's repository-level
  default setup must be set to not-configured or the two will conflict:

  ```bash
  gh api --method PATCH repos/OWNER/REPO/code-scanning/default-setup -f state=not-configured
  ```

## Adoption paths

Two paths bring a repository under management. Both require an explicit Library
`--pin` that already resolves to a published Aviato tag or branch; fresh writes
refuse to invent a default pin.

### Adopt an existing local repository

Plan first (no `--write`), review the planned scaffold, then apply:

```bash
aviato onboard . --profile python-library --pin X.Y.Z --docs           # plan only
aviato onboard . --profile python-library --pin X.Y.Z --docs --write   # apply the plan
```

`--docs` composes the opt-in docs deploy (§13.3). `onboard` mutates the local
tree only; open a PR with the scaffold and merge it through review. To adopt a
remote repository via a reviewable scaffold PR instead, use `--open-pr`:

```bash
aviato onboard OWNER/REPO --profile python-library --pin X.Y.Z --open-pr
```

### Provision a brand-new repository

`provision` creates the repository, applies staged protection, and scaffolds it
in one step. It is private by default; add `--public` only when the new
repository is intended to be public:

```bash
aviato provision OWNER/REPO --profile python-library --pin X.Y.Z --docs
```

## Post-merge convergence

Once the scaffold PR is merged, run the operator-initiated sequence that a live
adoption follows to bring GitHub's server-side state in line with the declaration.

**Apply the rulesets** resolved through the merged declaration:

```bash
aviato apply-rulesets OWNER/REPO --apply --declaration .github/aviato.yml
```

**Check drift coverage.** Scheduled file/settings drift detection is owned by the
[aviato-bot](https://github.com/amattas/aviato-bot) service (settings-event
webhooks plus a weekly fleet sweep), which opens file-drift proposals and files
settings-drift tracking issues. Confirm the repository is covered by pointing
`doctor` at the service:

```bash
export AVIATO_BOT_URL=https://aviato-bot.example
export AVIATO_BOT_STATUS_TOKEN=<repo-status bearer token>
aviato doctor .   # prints the bot status: line for this repo
```

**Reconcile settings drift** through the fail-closed consent gate. Settings are
never applied unattended: the operator adds the consent label to the tracking
issue, and `reconcile` binds the apply to a specific `DIFF_ID` — if the live diff
no longer matches, the command refuses rather than applying a stale change:

```bash
aviato reconcile . aviato-settings-drift --confirm DIFF_ID
```

**Register PyPI Trusted Publishing** (for profiles that publish to PyPI). Create
the protected `pypi` environment with at least one required reviewer, then
register the consumer's publishing workflow with the project. Enter exactly:
owner `OWNER`, repository `REPO`, workflow `aviato-ci.yml`, environment `pypi`.
The publishing job must stay in `aviato-ci.yml` so its OIDC identity matches the
registration — never fall back to an API token:

```bash
gh api --method PUT repos/OWNER/REPO/environments/pypi --input protection.json
gh api repos/OWNER/REPO/environments/pypi
```

**Enable Pages** when serving docs. Docs are always versioned onto `gh-pages`
when the profile has `docs: true`; to serve them, set `serve-pages: true` and
point Pages at the workflow build type:

```bash
gh api --method PUT repos/OWNER/REPO/pages -f build_type=workflow
```

**Verify** the managed posture:

```bash
aviato doctor .
```

See the [CLI reference](cli.md) for every subcommand and the
[release and docs model](releases-and-docs.md) for how versions publish once the
repository is live.
