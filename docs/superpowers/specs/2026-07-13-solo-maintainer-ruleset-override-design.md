# Solo-maintainer ruleset override design

**Status:** approved for implementation on 2026-07-13

## Problem

Aviato's branch ruleset requires one approving review. The `amattas/aviato`
repository currently has exactly one eligible reviewer, and that person is also
the author of PR #62. GitHub does not count an author's self-review, so the
repository's default approval count creates a permanent merge deadlock even
when every required check passes.

## Decision

Keep the Library-wide default at one approval and declare a repository-specific
override in `.github/aviato.yaml`:

```yaml
overrides:
  settings:
    default_branch:
      required_reviews: 0
```

The declaration is the durable source for Aviato's own exception. Applying
rulesets with `--declaration .github/aviato.yaml` resolves the override through
the existing composition and rendering path, so drift detection and
remediation converge on the same desired state.

This is a liveness exception, not bypass permission. The branch ruleset must
retain the pull-request rule, exact required checks, CodeQL thresholds, review
thread resolution, stale-review dismissal, deletion protection,
non-fast-forward protection, active enforcement, and an empty bypass-actor
list. The tag ruleset remains unchanged except for its already documented
metadata-pattern degradation.

The exception is valid only while the repository has no independent eligible
reviewer. Before or in the same settings change that grants another person or
team approval eligibility, the declaration must remove this override so the
profile default of one required approval is restored.

## Alternatives considered

1. **Add an administrator bypass actor.** Rejected because it creates standing
   authority to evade every ruleset gate, not just the impossible review count.
2. **Use one-off administrator merges.** Rejected as the normal path because it
   requires repeated exceptional authorization and leaves future pull requests
   structurally blocked.
3. **Set this repository's required-review count to zero.** Selected because it
   removes only the unsatisfiable gate while keeping all independent machine and
   immutability controls enforceable.

## Security and documentation

The threat model records the accepted absence of independent human review while
the exception is active. SEC-007 records the retained controls and live
ruleset evidence. The onboarding specification owns the exact eligibility and
reversal behavior. The traceability matrix links the declaration, tests, live
rulesets, and PR #62. No completed work is added to a backlog.

## Verification and rollout

1. Extend the existing SEC-007 governance test so it fails while the declaration
   and living documents omit this exception.
2. Add the declaration override and reconcile the specification, threat model,
   security control, traceability matrix, and active rollout plan.
3. Run focused tests and the strict repository gate.
4. Apply rulesets from the declaration, then read back both live rulesets and
   prove the approval count is zero while all other protected fields are
   unchanged.
5. Push once, wait for CI, merge PR #62 normally without `--admin`, update local
   `main`, and prune this completed design and its implementation plan after
   their durable content is owned by living documents.
