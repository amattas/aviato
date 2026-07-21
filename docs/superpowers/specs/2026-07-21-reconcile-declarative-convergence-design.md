# Reconcile Declarative Convergence Design

**Date:** 2026-07-21
**Status:** Approved design
**Issue:** [#115 — reconcile consent-gate ergonomics](https://github.com/amattas/aviato/issues/115)

## Summary

`aviato reconcile` will become a declaration-driven convergence command. The
consumer declaration and resolved Aviato profile define the desired repository
settings, GitHub permissions authorize the mutation, and apply-time
recomputation prevents stale writes.

The current GitHub-issue consent label is removed. It does not enforce
separation of duties: the implementation records the label granter but neither
identifies nor compares the operator who runs `reconcile`. Under Aviato's
single-operator model, the label is an additional ceremony rather than an
independent authorization boundary.

Tracking issues remain useful, but only as drift alerts. Scheduled drift scans
create or update them while drift exists and close them once both settings and
required rulesets are verifiably clean. Reconciliation does not require, read,
or comment on an issue.

## Goals

- Make the normal reconcile path interactive and understandable.
- Provide explicit noninteractive preview and apply modes.
- Remove issue labels and issue state from authorization.
- Keep every existing race, compatibility, and unmodeled-protection safeguard.
- Make a clean drift scan close resolved alert issues automatically.
- Preserve the consumer declaration and Git history as the record of intended
  policy, with GitHub's native logging as the platform-side record where
  available.

## Non-goals

- Multi-person approval or separation of duties. If required later, it must use
  a GitHub-native control such as protected environments or required reviewers.
- Changing how desired settings are declared, composed, or version-pinned.
- Introducing a persistent plan file or a diff token exchanged between separate
  CLI invocations.
- Automating or redesigning external-watch issues #119, #120, or #123.
- Implementing managed-block scaffolding from issue #116.
- Adding a new clean-worktree or default-branch requirement. Existing
  declaration and version-pin validation remains authoritative; operators are
  expected to commit declaration changes through their normal PR workflow.

## Command contract

### Interactive default

```console
aviato reconcile .
```

The command:

1. Loads the consumer declaration and resolves the desired settings.
2. Reads live GitHub settings and computes a structured reconcile plan.
3. Prints the complete classified diff.
4. Exits successfully without prompting when the diff is empty.
5. Otherwise prompts with a default of `no`.
6. On approval, immediately re-reads live state and applies only if the diff is
   unchanged.

If stdin is not an interactive terminal, this mode fails with a usage error and
directs the caller to choose `--preview` or `--apply` explicitly. EOF is treated
as a declined prompt. A deliberate decline is a successful cancellation and
does not mutate settings.

### Noninteractive preview

```console
aviato reconcile . --preview
```

Preview loads and prints the same reconcile plan but never prompts and never
calls a mutating platform method. A successful read and render exits zero
whether the repository is clean or drifted; the structured human-readable
status in stdout distinguishes those outcomes. Existing drift/doctor commands
remain the machine-oriented health gates.

### Noninteractive apply

```console
aviato reconcile . --apply
```

Apply prints the current plan, performs no prompt, re-reads live state, and
converges whatever live drift exists against the current resolved declaration.
It does not require an expected diff ID from a prior invocation. The explicit
flag establishes noninteractive mutation intent, while the in-invocation plan
identity and expected-live binding protect the write.

`--preview` and `--apply` are mutually exclusive. The positional issue argument
and `--confirm` option are removed.

## Core architecture

### Reconcile planner

The planner is read-only. It accepts the resolved desired settings and a live
platform snapshot and returns a `ReconcilePlan` containing:

- desired settings;
- live settings;
- classified changes and concrete live-to-desired values;
- the content-bound diff identity; and
- version compatibility information needed by the executor.

The diff identity remains an internal safety value. It is not printed as an
operator challenge and is not accepted as CLI input.

### Reconcile executor

The executor accepts the in-memory plan selected by the CLI. Immediately before
the privileged write, it:

1. re-reads live settings;
2. recomputes the diff against the plan's desired settings;
3. aborts if the recomputed identity differs from the displayed plan;
4. rechecks version compatibility and unmodeled-protection constraints; and
5. applies the complete desired settings with the final live snapshot passed as
   `expected_live`.

The executor never substitutes a newly discovered diff. A state change requires
the operator or automation to rerun the command and observe the new plan.

### CLI orchestration

The CLI owns mode selection, rendering, terminal detection, and prompting. Core
planning and execution remain interaction-free so they can be tested without a
terminal and reused by future bindings.

## Authorization and safety model

GitHub is the authorization boundary. A caller whose credentials cannot mutate
the repository settings is rejected by GitHub. Aviato does not duplicate that
decision through issue labels.

The following safeguards remain mandatory:

- Desired settings are recomputed from the local declaration and resolved
  profile using the existing validation path.
- An empty diff is an idempotent successful no-op.
- The displayed plan is bound to the apply attempt by its internal diff
  identity.
- Live settings are read again immediately before apply.
- The platform binding's `expected_live` check protects the remaining race
  window during multi-call GitHub updates.
- Unmodeled protections fail closed.
- Tool, declaration-pin, and recorded-marker compatibility checks fail closed;
  the existing explicit version-pin override remains available in interactive
  mode and with `--apply`, and is rejected with `--preview`.
- GitHub permission, transport, and API failures return nonzero without being
  reclassified as clean or applied.

The following consent-specific checks are removed:

- issue-open and unique-issue authorization gates;
- `aviato-consent:<diff-id>` label parsing;
- consent granter actor-type and current-role lookup;
- nonhuman issue-edit detection;
- consent revocation on changed or resolved drift; and
- operator-supplied diff confirmation.

## Outcomes and errors

- **Clean:** no drift; print a no-op result and exit zero in every mode.
- **Previewed:** drift printed under `--preview`; no mutation and exit zero.
- **Cancelled:** interactive operator declines or sends EOF; no mutation and
  exit zero.
- **Applied:** the complete desired settings landed with no unavailable
  features; exit zero.
- **Degraded:** GitHub applied the supported portion but one or more requested
  features were unavailable; print the exact skipped keys and exit nonzero.
- **Changed before apply:** the recomputed diff differs from the displayed plan;
  print both the fact of the change and rerun guidance, perform no write, and
  exit nonzero.
- **Write failure:** report that a partial mutation may have landed when the
  platform operation is not atomic; exit nonzero. No issue comment is attempted.
- **Usage or local declaration failure:** print actionable guidance and exit
  using the existing CLI usage/configuration error convention.

## Drift-issue lifecycle

The drift reporter, not `reconcile`, owns alert issues.

### Drift present

When settings or required rulesets drift:

- create a new issue if no canonical open issue exists;
- otherwise update the canonical open issue;
- include the classified settings changes and separate ruleset remediation;
- document `reconcile`, `reconcile --preview`, and `reconcile --apply`; and
- include no consent label or issue-specific reconcile argument.

### Drift clean

Only after live settings and all required rulesets are read successfully and
classified clean, close every open issue carrying the canonical drift key with
GitHub's completed state reason. If either surface is drifted, unknown, or
unreadable, leave the issues open.

A clean scan with no matching open issue is a no-op. If drift later recurs, the
open-only lookup creates a new issue rather than reopening a prior drift episode.

Closing is part of the scheduled scan's alert-state update. Any close API failure
makes the scan fail visibly; issues not yet closed remain open, and the next run
retries them. Settings are never changed as part of this path.

## Platform interface changes

The platform-neutral core interface gains an operation that closes all open
issues for a drift key as completed. This avoids making core reason about GitHub
issue numbers or duplicate-alert cleanup.

Reconciliation no longer uses `get_issue`, `comment_issue`, or
`revoke_consent`. The drift reporter retains issue discovery/update behavior and
uses the new close operation.

Consent-specific fields are removed from the core `Issue` model. GitHub timeline
reduction remains only if another feature still consumes it; otherwise the
consent event parser and role lookup are deleted.

## Migration and compatibility

This is an intentional clean break before 1.0:

- `aviato reconcile PATH ISSUE` is rejected with help showing
  `aviato reconcile PATH`.
- `--confirm` is rejected with help describing the interactive, `--preview`, and
  `--apply` modes.
- No compatibility shim silently ignores old authorization arguments.
- Existing open drift issues continue as alerts and are updated or closed by the
  next scan.
- Active labels beginning with `aviato-consent:` have no authority after the
  upgrade. The GitHub binding removes those legacy labels best-effort when it
  next updates or closes the affected issue; cleanup failure cannot restore
  authority or block a verified closure.

## Verification strategy

### CLI and orchestration

- Interactive drift: render, approve, and apply.
- Interactive decline and EOF: no mutation and successful cancellation.
- Plain mode on a non-TTY: usage failure naming the two explicit modes.
- `--preview`: complete output, no prompt, and no platform mutation.
- `--apply`: complete output, no prompt, and apply.
- `--preview` plus `--apply`: parser rejection.
- Empty diff: successful no-op in all three modes.
- Removed issue argument and `--confirm`: clear parser guidance.

### Core safety

- A live-state change between plan and execute aborts without mutation.
- The same diff executes using the final live snapshot.
- A change during the binding's write window fails through `expected_live`.
- Version mismatch and unknown marker versions fail closed.
- The explicit version override works only on a mutation path.
- Unmodeled protections fail closed.
- Permission and API failures are nonzero.
- Partial support returns a degraded, nonzero outcome naming every skipped key.

### Drift lifecycle

- Drift creates an issue when none is open.
- Repeated drift updates the canonical open issue.
- Clean settings plus clean rulesets closes every matching open issue.
- Any settings drift, ruleset drift, unknown probe, or read failure prevents
  closure.
- A later recurrence creates a new issue rather than reopening a closed one.
- Legacy consent labels are ignored for authorization and removed best-effort.

### Documentation and traceability

- Update the reconcile consent specification into a declaration-convergence
  specification.
- Update operator guidance and CLI examples.
- Update drift issue examples to show automatic closure and the three command
  modes.
- Remove consent-label requirements and tests from traceability.
- Link the implementation PR to issue #115 and close it only after verification
  passes.

## Acceptance criteria

The design is implemented when:

1. All three CLI modes behave as specified without accepting an issue or diff ID.
2. No reconcile mutation depends on GitHub issue state or consent labels.
3. Every apply remains bound to the displayed in-memory plan and final live
   snapshot.
4. Degraded and failed applications cannot report success.
5. A verified-clean drift scan automatically closes all matching open alerts.
6. Recurring drift creates a new alert episode.
7. Legacy consent labels confer no authority.
8. Focused and full repository verification pass with the updated
   specifications and traceability.
