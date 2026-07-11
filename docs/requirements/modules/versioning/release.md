<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

### 5.9 Library versioning & release

**Trigger:** changes merged to the Library's mainline.
**Actor:** the Library's own automation + Conventional Commit history (the commit
convention and the tag/floating-ref mechanics are part of the hosting-platform
binding, §2.14).
**Steps:** derive the next semantic version from Conventional Commit history
(patch / minor / major) → write the version via each affected language plug-in's
**version-source module** (§3.3) — the core never hardcodes a version location →
produce release artifacts (version bump, changelog, tagged release) → **advance
the floating major reference to the new release without consulting consumers**
(it is a published pointer; the Library cannot and does not query who consumes
it, per §2.2), **guarded monotonically per §8.14** — an out-of-order or re-run
release of an OLDER version never regresses the pointer (`aviato is-highest`
gates the move within the major line). The release process must not depend on a not-yet-existing release (§2.10):
in bootstrap, the release pipeline resolves its own module/action references
locally.

The release proposal must be mergeable under the policy's own branch
protection: a branch pushed with the platform's automation token never triggers
CI on its own (the platform suppresses events from that token), so the propose
phase **dispatches the caller workflow at the release branch** — manual
dispatch is exempt from that suppression — making the release PR report the
same required status checks as any human branch. Required-status-check rulesets
therefore stay enforceable with **no bypass actors**. A caller that has not yet
adopted the dispatch trigger fails soft: the dispatch step warns, the PR's
checks stay visibly pending, and the operator remediates by re-syncing the
caller (§5.3).

```mermaid
flowchart TD
    A["Changes merged to mainline"] --> B["Read Conventional Commit history"]
    B --> C{"Highest change type?"}
    C -- "breaking" --> Maj["Next = major"]
    C -- "feature" --> Min["Next = minor"]
    C -- "fix only" --> Pat["Next = patch"]
    Maj --> D["Write version via plug-in version-source module"]
    Min --> D
    Pat --> D
    D --> E["Produce release (version bump · changelog · tag)"]
    E --> F["Advance floating major reference UNCONDITIONALLY"]
    F --> G["Done"]
```
