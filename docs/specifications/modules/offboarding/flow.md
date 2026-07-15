<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

### 5.13 Offboarding (leave Aviato)

**Trigger:** operator removes a Consumer from Aviato management.
**Actor:** operator (local CLI).
**Steps:** strip managed markers from managed files (converting them to plain
operator-owned files) **or** remove them per operator choice → remove the
Consumer automation (the scheduled drift/report workflows) → delete the
declaration file. The change may be applied to a local checkout (`--write`) or
surfaced as a reviewable removal proposal (`--open-pr`), mirroring onboarding.
**The result must carry an explicit warning that offboarding removes the
always-on §2.13 security-baseline automation and stops Aviato managing this
repository's protection** — mirroring the §5.12 backward-movement warning, since
offboarding is the *maximal* protection reduction. Note the scope precisely: any
GitHub branch protection and rulesets Aviato applied **remain in place but become
unmanaged**; offboarding does **not** tear them down (an unattended privileged
teardown is out of scope, §2.x) — the operator removes them manually if full
protection removal is desired. After offboarding, no Aviato automation runs and
no markers remain to drift-check.

Before the first mutation, offboarding inspects the complete managed inventory,
the tracked and untracked marker universe, and the seed sidecar—not only outputs
that the current profile happens to render. Every inventoried file must still
match its receipt; every additional marker candidate must be a clean,
known-version artifact owned by the declared profile. Malformed, foreign,
hand-edited, ambiguous, symlinked, or unverified automation blocks the whole
operation. Seed-once paths are explicit operator-owned validation exclusions and
are never stripped or deleted.

Marker stripping or deletion, mandatory workflow deletion, declaration removal,
sidecar removal, and inventory removal form one journaled transition. Inventory
removal is last—even for a legacy consumer where that path is already absent—so
final acceptance always rescans and proves no non-seed managed marker remains.
An interruption therefore yields a resumable or rollback-capable journal instead
of a half-offboarded success. `--open-pr` executes this same transition in a
fresh clone and publishes all replacements and deletions; a no-diff rerun does
not create an empty proposal.

```mermaid
flowchart TD
    A["Operator: offboard Consumer"] --> P["Preflight inventory + full marker universe + seed exclusions"]
    P --> B{"All managed state clean and complete?"}
    B -- no --> X["FAIL CLOSED before mutation"]
    B -- yes --> K{"Keep passive files as plain, or remove?"}
    K -- keep --> C["Strip markers → operator-owned files"]
    K -- remove --> D["Delete managed files"]
    C --> E["Remove consumer drift/report automation"]
    D --> E
    E --> F["Delete declaration + sidecar"]
    F --> I["Delete inventory last; verify no managed markers remain"]
    I --> G["Apply locally or publish complete clone diff — WARN: removes §2.13 baseline automation; GitHub protection remains but UNMANAGED"]
```
