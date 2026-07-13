# Tag ruleset string-list 422 hotfix design

**Status:** approved design; implementation not started
**Date:** 2026-07-13

This document is a temporary execution aid, not the system of record. After the
hotfix and live verification are complete, move durable behavior and evidence
into the owning specification, security control, traceability row, and backlog;
then remove this design and its implementation plan from the branch tip.

## Problem

PR #60 made every rendered ruleset explicitly send `bypass_actors: []` and made
the ruleset submitter classify GitHub's structured response from both standard
error and standard output. The authorized live reapply then produced a response
shape not covered by the merged classifier:

```text
gh: Validation Failed (HTTP 422)
{"message":"Validation Failed","errors":["Invalid rule 'tag_name_pattern': "]}
```

The branch ruleset update succeeded and live readback proved the intended
zero-bypass/check/CodeQL posture. The tag ruleset remained in its already-safe
degraded state: zero bypass actors plus deletion and non-fast-forward rules.
However, the command exited nonzero because `_unsupported_tag_metadata_rule`
accepts structured error objects but ignores string entries in `errors`.

## Selected approach

Recognize only the exact live string-entry form as another correlated rejection
of the unsupported tag metadata rule. Keep all existing object-entry handling
and fail-closed behavior unchanged.

Inside a parsed `errors` list, a string entry may authorize the degraded retry
only when it matches this case-insensitive, whole-entry grammar after JSON
decoding:

```text
optional whitespace + Invalid rule + quoted tag_name_pattern + colon + optional whitespace
```

Conceptually, the matcher is equivalent to:

```regex
^\s*invalid\s+rule\s+["']tag_name_pattern["']\s*:\s*$
```

The surrounding combined response must still contain `HTTP 422`. The matcher
must inspect one entry at a time; separate entries cannot be combined to create
authorization.

## Rejected approaches

### Send every string entry through the existing broad text matcher

This is smaller mechanically, but it expands the downgrade boundary beyond the
observed GitHub response. Similar wording about a pattern value, condition, or
unrelated rule could be misclassified as an unsupported rule type.

### Leave the code unchanged and manage the degraded tag payload manually

The current live posture is safe, but every future Library ruleset apply would
exit nonzero on the same supported degradation. That contradicts the normative
onboarding behavior and turns a known production response into permanent manual
work.

## Behavior and data flow

1. `_submit_ruleset` continues combining non-empty standard error and standard
   output before raising `GitHubAPIError`.
2. `_unsupported_tag_metadata_rule` continues requiring `HTTP 422` and parsing
   the first JSON object from the combined response.
3. Existing structured object correlation remains unchanged.
4. A string error entry is checked only against the whole-entry grammar above.
5. On a match, `upsert_ruleset` removes only `tag_name_pattern` from a deep copy
   of the tag payload and submits the degraded payload once.
6. The degraded payload retains `bypass_actors: []`, targeting conditions,
   enforcement, deletion, and non-fast-forward protection.
7. Any non-match or failure of the one degraded retry propagates unchanged.

No new retry loop, error normalization layer, public API, or unrelated
refactoring is in scope.

## Test design

Use test-driven development against the exact live response.

The red regression test will simulate the generic 422 on standard error and the
JSON body with a string-list error on standard output. It will require:

- exactly two submissions;
- the first submission to contain the full payload;
- the second submission to omit only `tag_name_pattern`;
- `degraded_rules == ("tag_name_pattern",)`; and
- both temporary payload files to retain the existing cleanup and permission
  guarantees.

Focused classifier negatives will prove that no degraded retry occurs for:

- `Invalid rule 'deletion':`;
- `Invalid field 'tag_name_pattern':`;
- `Invalid rule 'tag_name_pattern': malformed regex`;
- correlation split across multiple string entries;
- the same text without HTTP 422; or
- permission, network, server, malformed-response, and other validation errors
  already covered by the suite.

After the red/green cycle, run the complete GitHub/ruleset tests and the strict
repository validation gate.

## Live verification and delivery

After automated verification and independent review:

1. Dry-render the `aviato-library` declaration and confirm both payloads still
   contain `bypass_actors: []`.
2. Run the hotfix CLI against `amattas/aviato` and require a successful command
   with only `tag_name_pattern` reported as degraded.
3. Read back both repository rulesets and require:
   - branch bypass actors are empty;
   - required contexts are exactly common lint, security heartbeat, and Python
     CI;
   - CodeQL thresholds are `none` and `high_or_higher`;
   - branch and tag deletion/non-fast-forward protections are active;
   - tag bypass actors are empty; and
   - tag metadata-pattern omission is the only degradation.
4. Update SEC-007, its traceability row, the security backlog, and the active
   rollout plan only from captured live evidence.
5. Leave PR #59 and release PR #42 untouched.
6. Remove this completed design and its implementation plan after their durable
   facts are incorporated into living documentation.
7. Publish one hotfix branch and pull request. The now-zero-bypass branch
   ruleset requires approval by a reviewer other than the author; do not weaken
   protection or recreate a bypass to merge it.

Success means future ruleset applies handle the observed GitHub response without
broadening the downgrade boundary, the live protection readback is exact, and
the durable records contain no unverified claims.
